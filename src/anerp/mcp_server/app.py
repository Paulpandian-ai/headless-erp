"""The MCP server: streamable HTTP (mounted at /mcp) and stdio (DESIGN.md §11)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from anerp import __version__
from anerp.core.envelope import Principal
from anerp.mcp_server import prompts, resources
from anerp.mcp_server.auth import current_principal, principal_from_env
from anerp.mcp_server.registry import call_tool, mcp_tools, to_result

log = logging.getLogger("anerp.mcp")

INSTRUCTIONS = (
    "anerp is a headless ERP kernel. Tools are business operations (not CRUD). Every write tool accepts "
    "mode='simulate' (no side effects, returns projected effects + policy decision) and mode='commit' "
    "(requires a unique idempotency_key; returns a signed receipt). Simulate before you commit. Errors "
    "come back with a stable code and retry_advice. The first line of every tool description is its "
    "signature, tool_name(required, optional?), with ? marking optional parameters. Read the prompts "
    "(procure_to_pay_playbook, order_to_cash_playbook, period_close_checklist) and the "
    "anerp://capabilities resource to plan."
)


def _principal(ctx: Any) -> Principal | None:
    principal = current_principal.get()
    if principal is not None:
        return principal
    request = getattr(ctx, "request", None)
    headers = getattr(request, "headers", None)
    if headers is not None:
        from anerp.mcp_server.auth import principal_from_token

        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return principal_from_token(auth[7:].strip())
    return None


def build_server(
    *,
    stdio_principal: Principal | None = None,
    tool_filter: Callable[[str], bool] | None = None,
    call_hook: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> Server[Any]:
    """`stdio_principal` binds every call to one principal (stdio transport, or a loopback
    server the eval harness runs in-process); `tool_filter` hides tools from the listing;
    `call_hook(name, arguments, result)` may replace the result the client sees after the
    kernel has processed the call (the eval harness injects transport faults with it)."""

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        tools = mcp_tools()
        if tool_filter is not None:
            tools = [t for t in tools if tool_filter(t.name)]
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        principal = stdio_principal or _principal(ctx)
        result = await anyio.to_thread.run_sync(call_tool, params.name, params.arguments, principal)
        if call_hook is not None:
            result = call_hook(params.name, params.arguments or {}, result)
        return to_result(result)

    async def on_list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=resources.list_resources())

    async def on_read_resource(
        ctx: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        uri = str(params.uri)
        mime, text = await anyio.to_thread.run_sync(resources.read_resource, uri)
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=params.uri, mime_type=mime, text=text)]
        )

    async def on_list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=prompts.list_prompts())

    async def on_get_prompt(
        ctx: Any, params: types.GetPromptRequestParams
    ) -> types.GetPromptResult:
        return prompts.get_prompt(params.name)

    return Server(
        "anerp",
        version=__version__,
        title="anerp agent-native ERP",
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
    )


def build_http_app(server: Server[Any] | None = None, path: str = "/mcp") -> Any:
    """Return (starlette_app, asgi_endpoint, server) for the streamable-HTTP transport.

    The endpoint is the raw ASGI handler wrapped in bearer auth; register it as a Route in the
    main FastAPI app (a Mount would redirect /mcp -> /mcp/). Stateless + JSON responses: every
    request carries its own bearer token, no server-side session state. The Starlette app's
    lifespan must be entered to run the session manager.
    """
    from anerp.mcp_server.auth import BearerAuthMiddleware

    server = server or build_server()
    starlette_app = server.streamable_http_app(
        streamable_http_path=path, stateless_http=True, json_response=True, host="0.0.0.0"
    )
    endpoint = BearerAuthMiddleware(starlette_app.routes[0].endpoint)  # type: ignore[attr-defined]
    return starlette_app, endpoint, server


async def run_stdio() -> None:
    """`anerp mcp --stdio`: the principal comes from ANERP_TOKEN / ANERP_ADMIN_TOKEN."""
    principal = principal_from_env()
    if principal is None:
        raise SystemExit(
            "stdio transport needs ANERP_TOKEN (or ANERP_ADMIN_TOKEN) set to a valid token"
        )
    server = build_server(stdio_principal=principal)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
