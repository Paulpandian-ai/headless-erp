"""Google provider (google-genai function calling). Untested without credentials."""

from __future__ import annotations

import os
from typing import Any

from anerp.a2a_agent.llm.base import LLMTurn, ToolCall

DEFAULT_MODEL = "gemini-2.5-pro"


class GoogleClient:
    def __init__(self, model: str | None = None) -> None:
        from google import genai

        self.client = genai.Client()
        self.model = model or os.environ.get("ANERP_LLM_MODEL", DEFAULT_MODEL)
        self._system = ""

    def start(self, system: str, user_text: str) -> list[Any]:
        self._system = system
        return [{"role": "user", "parts": [{"text": user_text}]}]

    def complete(self, system: str, messages: list[Any], tools: list[dict[str, Any]]) -> LLMTurn:
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters=_strip(t["input_schema"])
            )
            for t in tools
        ]
        response = self.client.models.generate_content(
            model=self.model,
            contents=messages,
            config=types.GenerateContentConfig(
                system_instruction=system, tools=[types.Tool(function_declarations=declarations)]
            ),
        )
        candidate = response.candidates[0]
        turn = LLMTurn(raw=candidate.content)
        for i, part in enumerate(candidate.content.parts or []):
            if getattr(part, "text", None):
                turn.text += part.text
            if getattr(part, "function_call", None):
                fc = part.function_call
                turn.tool_calls.append(
                    ToolCall(id=f"{fc.name}-{i}", name=fc.name, arguments=dict(fc.args or {}))
                )
        return turn

    def append_assistant(self, messages: list[Any], turn: LLMTurn) -> None:
        messages.append(turn.raw)

    def append_tool_results(
        self, messages: list[Any], results: list[tuple[ToolCall, str, bool]]
    ) -> None:
        from google.genai import types

        parts = [
            types.Part.from_function_response(name=call.name, response={"result": text})
            for call, text, _ in results
        ]
        messages.append(types.Content(role="user", parts=parts))


def _strip(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini rejects some JSON-schema keywords; keep the structural core."""
    drop = {"additionalProperties", "default", "title", "examples", "$defs"}
    if isinstance(schema, dict):
        return {
            k: (
                _strip(v)
                if isinstance(v, dict)
                else [_strip(x) if isinstance(x, dict) else x for x in v]
                if isinstance(v, list)
                else v
            )
            for k, v in schema.items()
            if k not in drop
        }
    return schema
