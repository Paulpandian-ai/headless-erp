"""Claude Agent SDK adapter: runs the narrative with the anerp MCP endpoint as an MCP server.

Requires `pip install claude-agent-sdk` and ANTHROPIC_API_KEY; only works against a RemoteSurface
(the SDK connects to the HTTP endpoint itself). Not exercised in CI.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import RemoteSurface, ToolSurface

DEFAULT_MODEL = "claude-opus-5"


class ClaudeAgentSDKClient:
    name = "claude_agent_sdk"
    needs_remote = True

    def __init__(self) -> None:
        self.model = os.environ.get("ANERP_ANTHROPIC_MODEL", DEFAULT_MODEL)
        # A scratch cwd so the harness loads no project settings, CLAUDE.md or skills.
        self._cwd = tempfile.mkdtemp(prefix="anerp-eval-claude-")

    def available(self) -> bool:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace:
        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, query

        if not isinstance(surface, RemoteSurface):
            return RunTrace(
                final_text="claude_agent_sdk needs a remote MCP endpoint (ANERP_URL)",
                error="needs_remote",
            )
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=NEUTRAL_SYSTEM_PROMPT,
            mcp_servers={
                "anerp": {
                    "type": "http",
                    "url": surface.url.rstrip("/") + "/mcp",
                    "headers": {"Authorization": f"Bearer {surface.token}"},
                }
            },
            tools=[],  # no built-in tools: the ERP is reachable only through MCP, like the others
            allowed_tools=["mcp__anerp__*"],
            permission_mode="bypassPermissions",
            max_turns=max_steps,
            cwd=self._cwd,
            setting_sources=[],
        )
        trace = RunTrace()

        async def go() -> None:
            async for message in query(prompt=narrative, options=options):
                kind = type(message).__name__
                content: Any = getattr(message, "content", None)
                if isinstance(content, list):
                    for block in content:
                        if (
                            getattr(block, "name", None)
                            and getattr(block, "input", None) is not None
                        ):
                            args = dict(block.input)
                            trace.tool_calls.append(
                                ToolCallRecord(
                                    str(block.name).replace("mcp__anerp__", ""),
                                    args,
                                    None,
                                    None,
                                    args.get("mode"),
                                )
                            )
                        elif getattr(block, "text", None) and kind == "AssistantMessage":
                            trace.final_text = block.text
                if kind == "ResultMessage":
                    trace.final_text = (
                        getattr(message, "result", trace.final_text) or trace.final_text
                    )
                    usage = getattr(message, "usage", None) or {}
                    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
                    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
                    # Comparable "tokens in" = everything the model read, cached or not.
                    trace.input_tokens = int(usage.get("input_tokens", 0) or 0) + cache_read
                    trace.input_tokens += cache_write
                    trace.output_tokens = int(usage.get("output_tokens", 0) or 0)
                    trace.extra["cache_read_input_tokens"] = cache_read
                    trace.extra["cache_creation_input_tokens"] = cache_write
                    cost = getattr(message, "total_cost_usd", None)
                    if cost is not None:
                        trace.extra["vendor_reported_cost_usd"] = float(cost)
                    trace.steps = int(getattr(message, "num_turns", 0) or 0)
                    if getattr(message, "subtype", "") == "error_max_turns":
                        trace.error = "max_steps"
                    elif getattr(message, "is_error", False):
                        trace.error = str(
                            getattr(message, "errors", None) or getattr(message, "subtype", "")
                        )

        anyio.run(go)
        return trace
