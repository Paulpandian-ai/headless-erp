"""`in_process` client: a neutral tool-calling loop over any ToolSurface using LLM_PROVIDER."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from anerp.a2a_agent.llm.base import LLMClient, ToolCall, make_client
from anerp.eval.clients.base import NEUTRAL_SYSTEM_PROMPT, RunTrace, ToolCallRecord
from anerp.eval.surface import ToolSurface


class InProcessLLMClient:
    name = "in_process"

    def __init__(self, provider: str | None = None) -> None:
        self.provider = provider or os.environ.get("LLM_PROVIDER", "none")
        self._llm: LLMClient | None = None

    def available(self) -> bool:
        return make_client(self.provider) is not None

    def _client(self) -> LLMClient:
        if self._llm is None:
            llm = make_client(self.provider)
            if llm is None:
                raise RuntimeError("LLM_PROVIDER is not configured")
            self._llm = llm
        return self._llm

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace:
        llm = self._client()
        tools = surface.list_tools()
        messages = llm.start(NEUTRAL_SYSTEM_PROMPT, narrative)
        trace = RunTrace()
        for _ in range(max_steps):
            turn = llm.complete(NEUTRAL_SYSTEM_PROMPT, messages, tools)
            trace.steps += 1
            trace.input_tokens += turn.usage.get("input_tokens", 0)
            trace.output_tokens += turn.usage.get("output_tokens", 0)
            llm.append_assistant(messages, turn)
            if not turn.tool_calls:
                trace.final_text = turn.text
                return trace
            results: list[tuple[ToolCall, str, bool]] = []
            for call in turn.tool_calls:
                t0 = time.perf_counter()
                out = surface.call(call.name, call.arguments)
                trace.tool_calls.append(
                    ToolCallRecord(
                        call.name,
                        call.arguments,
                        out.get("ok"),
                        (out.get("error") or {}).get("code"),
                        call.arguments.get("mode") if isinstance(call.arguments, dict) else None,
                        round((time.perf_counter() - t0) * 1000, 1),
                    )
                )
                results.append(
                    (call, json.dumps(out, default=str)[:20000], not out.get("ok", False))
                )
            llm.append_tool_results(messages, results)
        trace.final_text = "Stopped: step limit reached."
        trace.error = "max_steps"
        return trace


__all__: list[Any] = ["InProcessLLMClient"]
