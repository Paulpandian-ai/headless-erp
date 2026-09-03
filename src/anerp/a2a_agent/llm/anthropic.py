"""Anthropic provider (official `anthropic` SDK, Messages API with tool use)."""

from __future__ import annotations

import json
import os
from typing import Any

from anerp.a2a_agent.llm.base import LLMTurn, ToolCall

DEFAULT_MODEL = "claude-opus-5"


class AnthropicClient:
    def __init__(self, model: str | None = None) -> None:
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANERP_LLM_MODEL", DEFAULT_MODEL)

    def start(self, system: str, user_text: str) -> list[Any]:
        return [{"role": "user", "content": user_text}]

    def complete(self, system: str, messages: list[Any], tools: list[dict[str, Any]]) -> LLMTurn:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
            tools=[
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                }
                for t in tools
            ],
        )
        if response.stop_reason == "refusal":
            return LLMTurn(text="The model declined this request.", raw=response.content)
        turn = LLMTurn(
            raw=response.content,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
        for block in response.content:
            if block.type == "text":
                turn.text += block.text
            elif block.type == "tool_use":
                turn.tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        return turn

    def append_assistant(self, messages: list[Any], turn: LLMTurn) -> None:
        messages.append({"role": "assistant", "content": turn.raw})

    def append_tool_results(
        self, messages: list[Any], results: list[tuple[ToolCall, str, bool]]
    ) -> None:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": text,
                        "is_error": is_error,
                    }
                    for call, text, is_error in results
                ],
            }
        )


__all__ = ["AnthropicClient", "json"]
