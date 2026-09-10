"""Thin HTTP facade over the tool surface: POST /api/{query,simulate,commit}/{tool}.

The facade owns no business logic. It authenticates the bearer token exactly as the MCP
transport does, splits the JSON body into envelope + payload with the same adapter
(`mcp_server.registry.call_tool`), and forwards to `core.run_query` / `core.dispatch`. The
response body is the dict those functions return, serialized the same way MCP serializes it,
so a caller gets byte-for-byte what `tools/call` would have given for the same arguments.

Two consequences worth knowing:

* Scopes are not checked here. `dispatch` and `run_query` already refuse a token that lacks
  `tool.scope` with `FORBIDDEN`, so the facade inherits MCP's authorization unchanged.
* HTTP status is 200 for anything the kernel answered, including business errors -- read `ok`
  and `error.code` from the body. Only a request that fails to authenticate gets a non-200
  (401), which is the same thing the MCP transport does. Mapping error codes onto status codes
  would be logic the MCP surface does not have, and the two surfaces have to agree.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
from fastapi import APIRouter, Path, Request, Response

from anerp.core.envelope import Principal
from anerp.core.errors import RETRY_ADVICE, ErrorCode
from anerp.core.registry import BaseTool, QueryTool, WriteTool, registry
from anerp.mcp_server.auth import (
    bearer_token,
    principal_from_token,
    unauthorized_body,
    www_authenticate,
)
from anerp.mcp_server.registry import call_tool

router = APIRouter(prefix="/api", tags=["facade"])

_BODY_DESCRIPTION = (
    "Tool payload. Field names for each tool are the first line of its description "
    "(`tool_name(required, optional?)`, `?` marking optional) from `list_capabilities` or "
    "MCP `tools/list`; a VALIDATION_ERROR also lists them under `error.details.expected_fields`. "
    "On /api/simulate and /api/commit the envelope fields `idempotency_key`, `simulation_id` and "
    "`on_behalf_of` sit alongside the payload fields, exactly as in MCP `tools/call` arguments. "
    "An empty body means an empty payload."
)

_REQUEST_BODY: dict[str, Any] = {
    "required": False,
    "content": {
        "application/json": {
            "schema": {"type": "object", "additionalProperties": True},
            "description": _BODY_DESCRIPTION,
        }
    },
}

_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "The kernel's answer, identical to the MCP `tools/call` result. `ok` is false for "
            "business errors (VALIDATION_ERROR, POLICY_DENIED, REQUIRES_APPROVAL, FORBIDDEN, ...); "
            "the code and `retry_advice` are in `error`."
        ),
        "content": {"application/json": {"schema": {"type": "object"}}},
    },
    401: {
        "description": (
            "Missing or invalid bearer token. Carries a `request_id` like any other error, so "
            "the failure can be looked up with `explain_error` once a working token is in hand."
        ),
        "content": {"application/json": {"schema": {"type": "object"}}},
    },
}


def _json_response(body: dict[str, Any], status: int = 200) -> Response:
    """Serialize like MCP does (`default=str`) so both surfaces render values identically."""
    return Response(
        content=json.dumps(body, default=str),
        media_type="application/json",
        status_code=status,
    )


def _error(
    code: ErrorCode, message: str, *, mode: str, details: dict[str, Any] | None = None
) -> Response:
    return _json_response(
        {
            "ok": False,
            "mode": mode,
            "error": {
                "code": code.value,
                "message": message,
                "details": details or {},
                "retry_advice": RETRY_ADVICE[code],
            },
        }
    )


def _unauthorized(token: str | None, *, tool: str, mode: str) -> Response:
    headers = {"WWW-Authenticate": www_authenticate()} if token is None else {}
    return Response(
        content=json.dumps(unauthorized_body(tool=tool, mode=mode)),
        media_type="application/json",
        status_code=401,
        headers=headers,
    )


def _authenticate(authorization: str | None) -> tuple[Principal | None, str | None]:
    token = bearer_token(authorization)
    return principal_from_token(token), token


def _parse_body(raw: bytes) -> dict[str, Any]:
    """Raise ValueError for anything that is not a JSON object; empty body is an empty payload."""
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"body must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _kind_mismatch(tool: BaseTool, mode: str) -> Response | None:
    """The URL segment decides which of the two entry points runs; a mismatch is the caller's bug."""
    if mode == "query" and not isinstance(tool, QueryTool):
        return _error(
            ErrorCode.VALIDATION_ERROR,
            f"'{tool.name}' is a write tool; POST it to /api/simulate/{tool.name} or "
            f"/api/commit/{tool.name}",
            mode=mode,
            details={"tool": tool.name, "kind": tool.kind},
        )
    if mode != "query" and not isinstance(tool, WriteTool):
        return _error(
            ErrorCode.VALIDATION_ERROR,
            f"'{tool.name}' is a read-only tool; POST it to /api/query/{tool.name}",
            mode=mode,
            details={"tool": tool.name, "kind": tool.kind},
        )
    return None


async def _forward(request: Request, name: str, *, mode: str) -> Response:
    try:
        args = _parse_body(await request.body())
    except ValueError as exc:
        return _error(ErrorCode.VALIDATION_ERROR, f"invalid request body: {exc}", mode=mode)

    principal, token = await anyio.to_thread.run_sync(
        _authenticate, request.headers.get("authorization")
    )
    if principal is None:
        return _unauthorized(token, tool=name, mode=mode)

    tool = registry.get(name)
    if tool is not None and (mismatch := _kind_mismatch(tool, mode)) is not None:
        return mismatch

    if mode != "query":
        declared = args.get("mode")
        if declared is not None and declared != mode:
            return _error(
                ErrorCode.VALIDATION_ERROR,
                f"body says mode='{declared}' but the route is /api/{mode}; drop the field or "
                f"POST to /api/{declared}/{name}",
                mode=mode,
                details={"route_mode": mode, "body_mode": declared},
            )
        args["mode"] = mode

    # Unknown tool names fall through to call_tool, which answers NOT_FOUND like MCP does.
    result = await anyio.to_thread.run_sync(call_tool, name, args, principal)
    return _json_response(result)


@router.post(
    "/query/{tool}",
    summary="Run a read-only tool",
    description=(
        "Forwards to `core.run_query`. Requires the tool's read scope on the bearer token. "
        "Read-only: no events, no receipts, the session is always rolled back."
    ),
    responses=_RESPONSES,
    openapi_extra={"requestBody": _REQUEST_BODY},
)
async def query(
    request: Request,
    tool: str = Path(description="Query tool name, e.g. get_trial_balance."),
) -> Response:
    return await _forward(request, tool, mode="query")


@router.post(
    "/simulate/{tool}",
    summary="Simulate a write tool (no side effects)",
    description=(
        "Forwards to `core.dispatch` with `mode=simulate`: validation, projected effects and the "
        "policy decision, with nothing persisted. Returns a `simulation_id` you may pass to "
        "/api/commit to be refused with STALE_SIMULATION if the state moved underneath you."
    ),
    responses=_RESPONSES,
    openapi_extra={"requestBody": _REQUEST_BODY},
)
async def simulate(
    request: Request,
    tool: str = Path(description="Write tool name, e.g. create_purchase_order."),
) -> Response:
    return await _forward(request, tool, mode="simulate")


@router.post(
    "/commit/{tool}",
    summary="Commit a write tool",
    description=(
        "Forwards to `core.dispatch` with `mode=commit`. Requires a unique `idempotency_key` "
        "(8-128 chars) in the body; replaying the same key returns the original receipt with "
        "`status=replayed`. Simulate first."
    ),
    responses=_RESPONSES,
    openapi_extra={"requestBody": _REQUEST_BODY},
)
async def commit(
    request: Request,
    tool: str = Path(description="Write tool name, e.g. create_purchase_order."),
) -> Response:
    return await _forward(request, tool, mode="commit")


__all__ = ["router"]
