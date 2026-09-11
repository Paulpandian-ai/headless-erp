"""FastAPI application: /mcp (MCP over streamable HTTP), /api (HTTP facade), /a2a,
/events/stream, /healthz, well-known."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import select
from sse_starlette.sse import EventSourceResponse
from starlette.routing import Route

from anerp import __version__
from anerp.admin.tokens import bootstrap_admin
from anerp.config import get_settings
from anerp.core.ids import iso, new_ulid
from anerp.db import init_db, session_scope
from anerp.events.log import poll
from anerp.facade import router as facade_router
from anerp.ledger.models import PolicyVersion, ServerKey
from anerp.ledger.receipts import keyring
from anerp.mcp_server.app import build_http_app
from anerp.mcp_server.auth import (
    bearer_token,
    forbidden_body,
    principal_from_token,
    unauthorized_body,
)
from anerp.policy.engine import get_engine

log = logging.getLogger("anerp.server")


def startup_checks() -> None:
    """Idempotent boot: schema in dev/test (Alembic in deployments), bootstrap admin, active key, DB policy."""
    settings = get_settings()
    if settings.env in ("dev", "test") and settings.database_url.startswith("sqlite"):
        init_db()
    with session_scope() as s:
        bootstrap_admin(s)
        keyring.ensure_active(s)
        active = s.exec(select(PolicyVersion).where(PolicyVersion.is_active == True)).first()  # noqa: E712
        if active is not None:
            get_engine().replace(active.yaml_text)
            log.info("loaded policy version %s from database", active.version)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=get_settings().log_level)
    await asyncio.to_thread(startup_checks)
    async with app.state.mcp_app.router.lifespan_context(app.state.mcp_app):
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="anerp", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    mcp_app, mcp_endpoint, mcp_server = build_http_app()
    app.state.mcp_app = mcp_app
    app.state.mcp_server = mcp_server

    @app.middleware("http")
    async def correlation(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("x-request-id") or new_ulid()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    # Added last so it wraps everything, including the /mcp route and preflight requests.
    # allow_credentials stays False: every surface authenticates with a bearer header, never a
    # cookie, and "*" plus credentials is rejected by browsers anyway.
    if origins := settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id", "X-Request-Id"],
            expose_headers=["X-Request-Id"],
        )

    app.include_router(facade_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        with session_scope() as s:
            key = keyring.ensure_active(s)
            from anerp.events.log import latest_seq

            seq = latest_seq(s)
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.env,
            "signing_key_id": key.id,
            "event_seq": seq,
            "policy_version": get_engine().policy.version,
        }

    @app.get("/.well-known/anerp-keys.json")
    async def keys() -> dict[str, Any]:
        with session_scope() as s:
            rows = s.exec(select(ServerKey).order_by(ServerKey.created_at)).all()  # type: ignore[arg-type]
            return {
                "keys": [
                    {
                        "id": k.id,
                        "public_key_pem": k.public_key_pem,
                        "created_at": iso(k.created_at),
                        "retired_at": iso(k.retired_at),
                        "active": k.retired_at is None,
                    }
                    for k in rows
                ]
            }

    if settings.advertise_oauth:

        @app.get("/.well-known/oauth-protected-resource")
        async def oauth_metadata() -> dict[str, Any]:
            return {
                "resource": settings.public_url.rstrip("/") + "/mcp",
                "authorization_servers": [],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [
                    "procurement:write",
                    "procurement:approve",
                    "sales:write",
                    "finance:*",
                    "*:read",
                    "admin:*",
                ],
            }

    @app.get("/events/stream")
    async def events_stream(
        request: Request,
        after_seq: int = 0,
        types: str | None = None,
        max_events: int | None = None,
    ) -> Any:
        principal = principal_from_token(bearer_token(request.headers.get("authorization")))
        if principal is None:
            return JSONResponse(
                unauthorized_body(
                    tool="events_stream",
                    mode="stream",
                    message="the events stream needs a bearer token carrying events:read",
                ),
                status_code=401,
            )
        # A valid token without the scope is a 403, not a 401 (DESIGN.md §11), the same
        # answer `poll_events` gives through the dispatcher.
        if not principal.has_scope("events:read"):
            return JSONResponse(
                forbidden_body(
                    principal=principal,
                    tool="events_stream",
                    mode="stream",
                    required_scope="events:read",
                    message="token lacks scope 'events:read' required by the events stream",
                ),
                status_code=403,
            )
        wanted = [t for t in (types or "").split(",") if t] or None

        async def gen() -> AsyncIterator[dict[str, Any]]:
            cursor = after_seq
            sent = 0
            while True:
                if await request.is_disconnected():
                    break
                with session_scope() as s:
                    batch = poll(s, cursor, wanted, 100)
                for ev in batch:
                    cursor = ev["seq"]
                    sent += 1
                    yield {
                        "id": str(ev["seq"]),
                        "event": ev["type"],
                        "data": json.dumps(ev, default=str),
                    }
                    if max_events is not None and sent >= max_events:
                        return
                if not batch:
                    yield {"event": "keepalive", "data": json.dumps({"after_seq": cursor})}
                    await asyncio.sleep(1.0)

        return EventSourceResponse(gen())

    from anerp.a2a_agent.app import mount_a2a

    mount_a2a(app)
    app.router.routes.append(
        Route("/mcp", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"])
    )
    return app


app = create_app
