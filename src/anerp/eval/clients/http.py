"""MCP-over-HTTP client helper (used by the CLI, the eval runner and tests)."""

from __future__ import annotations

import json
from typing import Any

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _client(url: str, token: str, transport: Any = None) -> httpx2.AsyncClient:
    kwargs: dict[str, Any] = {
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": httpx2.Timeout(60.0, read=300.0),
    }
    if transport is not None:
        kwargs["transport"] = transport
    return httpx2.AsyncClient(**kwargs)


async def call_tool_async(
    url: str, token: str, name: str, arguments: dict[str, Any], transport: Any = None
) -> dict[str, Any]:
    async with (
        _client(url, token, transport) as http,
        streamable_http_client(
            url.rstrip("/") + "/mcp" if not url.endswith("/mcp") else url, http_client=http
        ) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, arguments)
        return _unwrap(result)


def _unwrap(result: Any) -> dict[str, Any]:
    if getattr(result, "structured_content", None):
        return dict(result.structured_content)
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", "") == "text":
            return json.loads(block.text)
    return {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "empty MCP result"}}


def call_tool_http(url: str, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return anyio.run(call_tool_async, url, token, name, arguments)
