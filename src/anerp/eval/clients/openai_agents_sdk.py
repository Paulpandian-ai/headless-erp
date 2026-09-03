"""OpenAI Agents SDK adapter (package `openai-agents`), MCP over streamable HTTP. Not run in CI."""

from __future__ import annotations

import os

from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import RemoteSurface, ToolSurface


class OpenAIAgentsClient:
    name = "openai_agents_sdk"

    def available(self) -> bool:
        try:
            import agents  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("OPENAI_API_KEY"))

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace:
        import anyio
        from agents import Agent, Runner
        from agents.mcp import MCPServerStreamableHttp

        if not isinstance(surface, RemoteSurface):
            return RunTrace(
                final_text="openai_agents_sdk needs a remote MCP endpoint (ANERP_URL)",
                error="needs_remote",
            )
        trace = RunTrace()

        async def go() -> None:
            async with MCPServerStreamableHttp(
                name="anerp",
                params={
                    "url": surface.url.rstrip("/") + "/mcp",
                    "headers": {"Authorization": f"Bearer {surface.token}"},
                },
            ) as server:
                agent = Agent(
                    name="ops-assistant",
                    instructions=NEUTRAL_SYSTEM_PROMPT,
                    mcp_servers=[server],
                    model=os.environ.get("ANERP_LLM_MODEL", "gpt-5"),
                )
                result = await Runner.run(agent, narrative, max_turns=max_steps)
                trace.final_text = str(result.final_output)
                for item in result.new_items:
                    raw = getattr(item, "raw_item", None)
                    name = getattr(raw, "name", None)
                    if name and hasattr(raw, "arguments"):
                        import json

                        args = json.loads(raw.arguments or "{}")
                        trace.tool_calls.append(
                            ToolCallRecord(name, args, None, None, args.get("mode"))
                        )
                usage = getattr(result, "context_wrapper", None)
                if usage and getattr(usage, "usage", None):
                    trace.input_tokens = usage.usage.input_tokens
                    trace.output_tokens = usage.usage.output_tokens

        anyio.run(go)
        return trace
