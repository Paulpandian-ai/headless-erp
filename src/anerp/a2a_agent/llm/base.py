"""Provider-neutral LLM interface for the internal tool-calling loop (DESIGN.md §12)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # provider-native assistant message to echo back into history
    usage: dict[str, int] = field(default_factory=dict)


class LLMClient(Protocol):
    """One provider-specific implementation per file under a2a_agent/llm/."""

    def start(self, system: str, user_text: str) -> list[Any]:
        """Return the initial provider-native message list."""

    def complete(self, system: str, messages: list[Any], tools: list[dict[str, Any]]) -> LLMTurn:
        """One model call. `tools` are MCP-style {name, description, input_schema}."""

    def append_assistant(self, messages: list[Any], turn: LLMTurn) -> None: ...

    def append_tool_results(
        self, messages: list[Any], results: list[tuple[ToolCall, str, bool]]
    ) -> None:
        """results: (call, json_text, is_error)."""


def make_client(provider: str | None = None) -> LLMClient | None:
    provider = provider or os.environ.get("LLM_PROVIDER", "none")
    if provider == "anthropic":
        from anerp.a2a_agent.llm.anthropic import AnthropicClient

        return AnthropicClient()
    if provider == "openai":
        from anerp.a2a_agent.llm.openai import OpenAIClient

        return OpenAIClient()
    if provider == "google":
        from anerp.a2a_agent.llm.google import GoogleClient

        return GoogleClient()
    return None
