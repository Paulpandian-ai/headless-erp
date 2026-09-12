"""OpenAI Agents SDK adapter (package `openai-agents`), MCP over streamable HTTP. Not run in CI."""

from __future__ import annotations

import json
import os

from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import RemoteSurface, ToolSurface

DEFAULT_MODEL = "gpt-5"


class OpenAIAgentsClient:
    name = "openai_agents_sdk"
    needs_remote = True

    def __init__(self) -> None:
        self.model = os.environ.get("ANERP_OPENAI_MODEL", DEFAULT_MODEL)

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
        from agents import Agent, MaxTurnsExceeded, Runner, set_default_openai_client
        from agents.mcp import MCPServerStreamableHttp
        from openai import AsyncOpenAI

        # A run reads ~0.5M tokens over a minute or two; an org's tokens-per-minute limit is
        # routinely hit mid-run. The SDK's default 2 retries (sub-10 s) cannot ride that out;
        # the client honours `retry-after` and backs off between attempts.
        set_default_openai_client(
            AsyncOpenAI(max_retries=int(os.environ.get("ANERP_OPENAI_MAX_RETRIES", "10")))
        )

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
                    "timeout": 60,
                },
                client_session_timeout_seconds=120,
                cache_tools_list=True,
            ) as server:
                agent = Agent(
                    name="ops-assistant",
                    instructions=NEUTRAL_SYSTEM_PROMPT,
                    mcp_servers=[server],
                    model=self.model,
                )
                # Streamed so tool calls are recorded even when the run ends in MaxTurnsExceeded.
                result = Runner.run_streamed(agent, narrative, max_turns=max_steps)
                try:
                    async for event in result.stream_events():
                        item = getattr(event, "item", None)
                        if getattr(item, "type", None) != "tool_call_item":
                            continue
                        raw = item.raw_item
                        name = getattr(raw, "name", None)
                        if name and hasattr(raw, "arguments"):
                            args = json.loads(raw.arguments or "{}")
                            trace.tool_calls.append(
                                ToolCallRecord(name, args, None, None, args.get("mode"))
                            )
                    trace.final_text = str(result.final_output)
                except MaxTurnsExceeded:
                    trace.final_text = "Stopped: step limit reached."
                    trace.error = "max_steps"
                usage = result.context_wrapper.usage
                trace.input_tokens = int(usage.input_tokens or 0)
                trace.output_tokens = int(usage.output_tokens or 0)
                trace.steps = int(usage.requests or 0)
                details = getattr(usage, "input_tokens_details", None)
                if details is not None:
                    trace.extra["cache_read_input_tokens"] = int(
                        getattr(details, "cached_tokens", 0) or 0
                    )
                details = getattr(usage, "output_tokens_details", None)
                if details is not None:
                    trace.extra["reasoning_tokens"] = int(
                        getattr(details, "reasoning_tokens", 0) or 0
                    )

        anyio.run(go)
        return trace
