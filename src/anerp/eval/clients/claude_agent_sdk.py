"""Claude Agent SDK adapter: runs the narrative with the anerp MCP endpoint as an MCP server.

Requires `pip install claude-agent-sdk` and ANTHROPIC_API_KEY; only works against a RemoteSurface
(the SDK connects to the HTTP endpoint itself). Not exercised in CI.
"""

from __future__ import annotations

import os
from typing import Any

from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import RemoteSurface, ToolSurface


class ClaudeAgentSDKClient:
    name = "claude_agent_sdk"

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
            system_prompt=NEUTRAL_SYSTEM_PROMPT,
            mcp_servers={
                "anerp": {
                    "type": "http",
                    "url": surface.url.rstrip("/") + "/mcp",
                    "headers": {"Authorization": f"Bearer {surface.token}"},
                }
            },
            allowed_tools=["mcp__anerp__*"],
            permission_mode="bypassPermissions",
            max_turns=max_steps,
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
                    trace.input_tokens = int(usage.get("input_tokens", 0))
                    trace.output_tokens = int(usage.get("output_tokens", 0))
                    trace.steps = int(getattr(message, "num_turns", 0) or 0)

        anyio.run(go)
        return trace
