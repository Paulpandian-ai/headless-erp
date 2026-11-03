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

DEFAULT_MODEL = "claude-sonnet-5-5"


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
        # What the vendor says served the run (the API response's `model`), not the id we asked
        # for; and the CLI's cost basis, which is "list" only when it knows the model's prices.
        served: set[str] = set()
        cost_basis: set[str] = set()

        async def go() -> None:
            async for message in query(prompt=narrative, options=options):
                kind = type(message).__name__
                model = getattr(message, "model", None)
                if kind == "AssistantMessage" and model and not str(model).startswith("<"):
                    served.add(str(model))  # "<synthetic>" marks CLI-made messages
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
                    for used_model, info in (getattr(message, "model_usage", None) or {}).items():
                        served.add(str(used_model))
                        if isinstance(info, dict) and info.get("costBasis"):
                            cost_basis.add(str(info["costBasis"]))
                    if getattr(message, "subtype", "") == "error_max_turns":
                        trace.error = "max_steps"
                    elif getattr(message, "is_error", False):
                        trace.error = str(
                            getattr(message, "errors", None) or getattr(message, "subtype", "")
                        )

        try:
            anyio.run(go)
        except Exception as exc:
            # The SDK raises after yielding the error_max_turns result. Exhausting the step
            # limit is an outcome, not a client failure: keep the trace gathered so far.
            if trace.error != "max_steps" and "maximum number of turns" not in str(exc):
                raise
            trace.error = "max_steps"
            trace.final_text = trace.final_text or "Stopped: step limit reached."
        trace.extra["served_models"] = sorted(served)
        if cost_basis:
            trace.extra["cost_basis"] = sorted(cost_basis)
        if cost_basis - {"list"} and "vendor_reported_cost_usd" in trace.extra:
            # The CLI did not know this model's prices and guessed: not a vendor figure.
            trace.extra["cli_estimated_cost_usd"] = trace.extra.pop("vendor_reported_cost_usd")
        return trace
