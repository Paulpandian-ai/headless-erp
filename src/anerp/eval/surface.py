"""Tool surfaces the eval clients talk to: treatment (agent-native), control (CRUD), remote (HTTP)."""

from __future__ import annotations

from typing import Any, Protocol

from anerp.core.envelope import Principal


class ToolSurface(Protocol):
    name: str

    def list_tools(self) -> list[dict[str, Any]]: ...

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


EVAL_AGENT_SCOPES = [
    "procurement:write",
    "procurement:receive",
    "sales:write",
    "finance:*",
    "masterdata:write",
    "*:read",
    "approvals:write",
]


class TreatmentSurface:
    name = "treatment"

    def __init__(self, actor_id: str = "agent:eval") -> None:
        self.principal = Principal(subject=actor_id, kind="agent", scopes=EVAL_AGENT_SCOPES)

    def list_tools(self) -> list[dict[str, Any]]:
        from anerp.mcp_server.registry import mcp_tools

        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in mcp_tools()
            if not t.name.startswith(("mint_", "revoke_", "update_policy", "rotate_", "reset_"))
        ]

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from anerp.mcp_server.registry import call_tool

        return call_tool(name, args, self.principal)


class ControlSurface:
    name = "control"

    def list_tools(self) -> list[dict[str, Any]]:
        from anerp.eval.crud_server import crud_tools

        return crud_tools()

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from anerp.eval.crud_server import crud_call

        return crud_call(name, args)


class RemoteSurface:
    """The deployed anerp MCP endpoint (treatment) reached with a token."""

    name = "treatment"

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self._tools: list[dict[str, Any]] | None = None

    def list_tools(self) -> list[dict[str, Any]]:
        if self._tools is None:
            import anyio
            import httpx2
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            async def _list() -> list[dict[str, Any]]:
                async with (
                    httpx2.AsyncClient(headers={"Authorization": f"Bearer {self.token}"}) as http,
                    streamable_http_client(self.url.rstrip("/") + "/mcp", http_client=http) as (
                        r,
                        w,
                    ),
                    ClientSession(r, w) as session,
                ):
                    await session.initialize()
                    tools = await session.list_tools()
                    return [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "input_schema": t.input_schema,
                        }
                        for t in tools.tools
                    ]

            self._tools = anyio.run(_list)
        return self._tools

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from anerp.eval.clients.http import call_tool_http

        return call_tool_http(self.url, self.token, name, args)
