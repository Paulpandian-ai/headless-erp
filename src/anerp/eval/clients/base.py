"""Client adapter contract for the eval matrix (DESIGN.md §14.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from anerp.eval.surface import ToolSurface

NEUTRAL_SYSTEM_PROMPT = (
    "You are an operations assistant for a small company. You can act on the company's ERP only "
    "through the tools provided. Complete the manager's request carefully and completely, verify "
    "the outcome, and finish with a short plain-text report of what you did, including any document "
    "numbers, and anything you could not do and why."
)


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    ok: bool | None
    error_code: str | None = None
    mode: str | None = None
    latency_ms: float = 0.0


@dataclass
class RunTrace:
    final_text: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    steps: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_text": self.final_text,
            "tool_calls": [vars(c) for c in self.tool_calls],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "steps": self.steps,
            "error": self.error,
        }


class EvalClient(Protocol):
    name: str

    def available(self) -> bool: ...

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace: ...
