"""Rule and result models for the policy layer (DESIGN.md §9)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Effect = Literal["deny", "requires_approval", "warn"]
Decision = Literal["allow", "deny", "requires_approval"]


class Rule(BaseModel):
    id: str
    applies_to: list[str] = Field(default_factory=list)  # tool names, "@group", or "*"
    effect: Effect
    condition: str
    error_code: str | None = None  # deny only; defaults to POLICY_DENIED
    message: str = ""
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class PolicySet(BaseModel):
    version: int = 1
    groups: dict[str, list[str]] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)


class PolicyResult(BaseModel):
    decision: Decision = "allow"
    rules_evaluated: list[str] = Field(default_factory=list)
    rules_triggered: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    policy_version: int = 0
    policy_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()
