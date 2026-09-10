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
from anerp.core.errors import RETRY_ADVICE, ErrorCode
from anerp.core.requestlog import log_auth_failure
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


def www_authenticate() -> str:
    """The WWW-Authenticate value for a request that carried no token (RFC 9728 when enabled)."""
    settings = get_settings()
    if settings.advertise_oauth:
        url = settings.public_url.rstrip("/") + "/.well-known/oauth-protected-resource"
        return f'Bearer resource_metadata="{url}"'
    return "Bearer"


UNAUTHORIZED_MESSAGE = "missing or invalid bearer token; send Authorization: Bearer <token>"


def unauthorized_body(
    *, tool: str = "<transport>", mode: str = "auth", message: str = UNAUTHORIZED_MESSAGE
) -> dict[str, Any]:
    """The 401 body shared by every HTTP surface (MCP transport, /api facade, /events/stream).

    Shaped like every other anerp error response: `ok`, `mode`, `request_id`, `error`. The
    request_id is written to the request log, so a caller that gets a token can hand it to
    `explain_error` exactly as it would for a POLICY_DENIED (DESIGN.md §7.7).
    """
    request_id = log_auth_failure(tool=tool, mode=mode, message=message)
    return {
        "ok": False,
        "mode": mode,
        "request_id": request_id,
        "error": {
            "code": ErrorCode.UNAUTHORIZED.value,
            "message": message,
            "details": {},
            "retry_advice": RETRY_ADVICE[ErrorCode.UNAUTHORIZED],
        },
    }


def bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an Authorization header value, or None when absent/not bearer."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:].strip() or None


def _www_authenticate() -> list[tuple[bytes, bytes]]:
    return [(b"www-authenticate", www_authenticate().encode())]


class BearerAuthMiddleware:
    """ASGI middleware: resolve the bearer token to a Principal, else 401 with the anerp error shape."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        token = bearer_token(headers.get("authorization"))
        principal = principal_from_token(token)
        if principal is None:
            # The MCP JSON-RPC body is not parsed here, so the tool name is not yet known.
            body = json.dumps(unauthorized_body(tool="mcp")).encode()
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
