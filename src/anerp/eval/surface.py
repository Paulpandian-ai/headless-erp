"""Tool surfaces the eval clients talk to: treatment (agent-native), control (CRUD), remote (HTTP)."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Protocol

from anerp.core.envelope import Principal

HIDDEN_FROM_AGENTS = ("mint_", "revoke_", "update_policy", "rotate_", "reset_")
"""Admin tools the eval agents never see (their scopes would refuse them anyway)."""


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
            if not t.name.startswith(HIDDEN_FROM_AGENTS)
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
    """An MCP endpoint over streamable HTTP reached with a bearer token: the deployed anerp server
    (treatment) or the locally served CRUD baseline (control, see `crud_server.serve_http`)."""

    def __init__(self, url: str, token: str, name: str = "treatment") -> None:
        self.name = name
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


class LoopbackMcp:
    """A low-level MCP `Server` served on 127.0.0.1 over streamable HTTP from a background thread
    of the harness process, so SDK clients (which only speak MCP over HTTP) reach the in-process
    kernel. Treatment and control are served this way side by side, against the same database,
    so the two arms differ in nothing but the tool surface. No auth: loopback only."""

    def __init__(self, server: Any, name: str, host: str = "127.0.0.1", port: int = 0) -> None:
        import uvicorn

        if port == 0:
            with socket.socket() as sock:
                sock.bind((host, 0))
                port = sock.getsockname()[1]
        self.name = name
        self.host, self.port = host, port
        self.url = f"http://{host}:{port}"
        app = server.streamable_http_app(
            streamable_http_path="/mcp", stateless_http=True, json_response=True, host=host
        )
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="warning", lifespan="on")
        )
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name=f"mcp-loopback-{name}"
        )

    def start(self) -> LoopbackMcp:
        self._thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with socket.create_connection((self.host, self.port), timeout=0.5):
                    return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"the {self.name} loopback MCP server did not start")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)

    def surface(self) -> RemoteSurface:
        return RemoteSurface(self.url, "none", name=self.name)


def treatment_loopback(actor_id: str = "agent:eval", call_hook: Any = None) -> LoopbackMcp:
    """The agent-native surface, bound to the same scoped agent principal TreatmentSurface uses.
    `call_hook(name, args, result)` may replace what the client sees (fault injection)."""
    from anerp.mcp_server.app import build_server

    principal = Principal(subject=actor_id, kind="agent", scopes=EVAL_AGENT_SCOPES)
    server = build_server(
        stdio_principal=principal,
        tool_filter=lambda name: not name.startswith(HIDDEN_FROM_AGENTS),
        call_hook=call_hook,
    )
    return LoopbackMcp(server, "treatment")


def control_loopback() -> LoopbackMcp:
    """The CRUD baseline (BASELINE ONLY) on its own loopback port."""
    from anerp.eval.crud_server import build_crud_mcp_server

    return LoopbackMcp(build_crud_mcp_server(), "control")
