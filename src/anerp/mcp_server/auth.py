"""Bearer-token auth for the HTTP transports (DESIGN.md §11). Tokens are hashed with a server pepper."""

from __future__ import annotations

import contextvars
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from anerp.admin.tokens import resolve_token
from anerp.config import get_settings
from anerp.core.envelope import Principal
from anerp.db import session_scope

log = logging.getLogger("anerp.auth")

current_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "anerp_principal", default=None
)

ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]


def principal_from_token(token: str | None) -> Principal | None:
    if not token:
        return None
    with session_scope() as s:
        return resolve_token(s, token)


def principal_from_env() -> Principal | None:
    """stdio transport: the token comes from ANERP_TOKEN (or ANERP_ADMIN_TOKEN) in the environment."""
    token = os.environ.get("ANERP_TOKEN") or os.environ.get("ANERP_ADMIN_TOKEN")
    return principal_from_token(token)


def _www_authenticate() -> list[tuple[bytes, bytes]]:
    settings = get_settings()
    if settings.advertise_oauth:
        url = settings.public_url.rstrip("/") + "/.well-known/oauth-protected-resource"
        return [(b"www-authenticate", f'Bearer resource_metadata="{url}"'.encode())]
    return [(b"www-authenticate", b"Bearer")]


class BearerAuthMiddleware:
    """ASGI middleware: resolve the bearer token to a Principal, else 401 with the anerp error shape."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        principal = principal_from_token(token)
        if principal is None:
            body = json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "missing or invalid bearer token",
                        "retry_advice": "Obtain a valid bearer token (Authorization: Bearer <token>).",
                    },
                }
            ).encode()
            extra = _www_authenticate() if token is None else []
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        *extra,
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        reset = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(reset)
