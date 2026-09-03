"""Operation envelope and principal models (DESIGN.md §6.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Mode = Literal["simulate", "commit"]
ActorKind = Literal["agent", "human", "admin"]


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=128)
    kind: ActorKind = "agent"
    on_behalf_of: str | None = Field(default=None, max_length=128)


class Envelope(BaseModel):
    """Everything the dispatcher needs for one write operation."""

    model_config = ConfigDict(extra="forbid")
    tool: str
    mode: Mode = "simulate"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    simulation_id: str | None = None
    actor: Actor
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _commit_needs_key(self) -> Envelope:
        if self.mode == "commit" and not self.idempotency_key:
            raise ValueError("idempotency_key is required when mode='commit'")
        return self


class Principal(BaseModel):
    """Authenticated caller derived from an API token."""

    subject: str
    kind: ActorKind
    scopes: list[str]
    token_id: str | None = None

    def has_scope(self, required: str) -> bool:
        return scope_matches(self.scopes, required)

    def to_actor(self, on_behalf_of: str | None = None) -> Actor:
        return Actor(id=self.subject, kind=self.kind, on_behalf_of=on_behalf_of)


def scope_matches(granted: list[str], required: str) -> bool:
    """`admin:*` and `*` grant everything; `module:*` grants a module; `*:read` grants all reads."""
    if not required:
        return True
    req_mod, _, req_action = required.partition(":")
    for s in granted:
        if s in ("*", "admin:*", required):
            return True
        mod, _, action = s.partition(":")
        if action == "*" and mod == req_mod:
            return True
        if mod == "*" and action == req_action:
            return True
        # `finance:*` covers `finance:ap:write`; `*:write` covers `finance:ap:write`
        if action == "*" and req_mod == mod:
            return True
        if mod == "*" and required.endswith(":" + action):
            return True
    return False


def scope_subset(child: list[str], parent: list[str]) -> bool:
    """True when every scope in `child` is granted by `parent` (used by mint_token)."""
    return all(scope_matches(parent, c) or c in parent for c in child)
