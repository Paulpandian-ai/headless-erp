"""OpenAI provider (Chat Completions with function calling). Untested without credentials."""

from __future__ import annotations

import json
import os
from typing import Any

from anerp.a2a_agent.llm.base import LLMTurn, ToolCall

DEFAULT_MODEL = "gpt-5"


class OpenAIClient:
    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model or os.environ.get("ANERP_LLM_MODEL", DEFAULT_MODEL)

    def start(self, system: str, user_text: str) -> list[Any]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user_text}]

    def complete(self, system: str, messages: list[Any], tools: list[dict[str, Any]]) -> LLMTurn:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ],
        )
        msg = response.choices[0].message
        turn = LLMTurn(text=msg.content or "", raw=msg)
        for tc in msg.tool_calls or []:
            turn.tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments or "{}"),
                )
            )
        if response.usage:
            turn.usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        return turn

    def append_assistant(self, messages: list[Any], turn: LLMTurn) -> None:
        messages.append(turn.raw)

    def append_tool_results(
        self, messages: list[Any], results: list[tuple[ToolCall, str, bool]]
    ) -> None:
        for call, text, _ in results:
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
