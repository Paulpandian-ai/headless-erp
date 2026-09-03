"""PolicyEngine.evaluate(tool, facts, actor) -> PolicyResult, identical in simulate and commit."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from anerp.config import get_settings
from anerp.core.hashing import sha256_hex
from anerp.policy.evaluator import compile_expression
from anerp.policy.evaluator import evaluate as _eval
from anerp.policy.loader import load_policy_file, parse_policy_yaml
from anerp.policy.rules import PolicyResult, PolicySet, Rule

_DEFAULT_YAML = Path(__file__).resolve().parents[3] / "policies" / "default.yaml"


class PolicyEngine:
    def __init__(self, policy: PolicySet | None = None, yaml_text: str = "") -> None:
        self.policy = policy or PolicySet()
        self.yaml_text = yaml_text
        self.policy_hash = sha256_hex(yaml_text) if yaml_text else ""
        self._compiled: dict[str, ast.Expression] = {}
        self._compile()

    def _compile(self) -> None:
        self._compiled = {r.id: compile_expression(r.condition) for r in self.policy.rules}

    @classmethod
    def from_yaml(cls, text: str) -> PolicyEngine:
        return cls(parse_policy_yaml(text), text)

    @classmethod
    def from_file(cls, path: str | Path) -> PolicyEngine:
        text = Path(path).read_text()
        return cls(load_policy_file(path), text)

    def replace(self, text: str) -> None:
        new = parse_policy_yaml(text)
        self.policy = new
        self.yaml_text = text
        self.policy_hash = sha256_hex(text)
        self._compile()

    # ------------------------------------------------------------------------------
    def _applies(self, rule: Rule, tool_name: str) -> bool:
        for target in rule.applies_to:
            if target == "*" or target == tool_name:
                return True
            if target.startswith("@") and tool_name in self.policy.groups.get(target[1:], []):
                return True
        return False

    def evaluate(
        self, tool_name: str, facts: dict[str, Any], actor: dict[str, Any]
    ) -> PolicyResult:
        result = PolicyResult(policy_version=self.policy.version, policy_hash=self.policy_hash)
        scope: dict[str, Any] = {
            "tool": tool_name,
            "actor": actor,
            "params": self.policy.params,
            **facts,
        }
        for rule in self.policy.rules:
            if not self._applies(rule, tool_name):
                continue
            result.rules_evaluated.append(rule.id)
            scope["rule"] = rule.params
            fired = bool(_eval(self._compiled[rule.id], scope))
            if not fired:
                continue
            message = _format(rule.message or rule.description or rule.id, scope)
            result.rules_triggered.append(rule.id)
            if rule.effect == "warn":
                result.warnings.append(f"{rule.id}: {message}")
                continue
            result.reasons.append(f"{rule.id}: {message}")
            if rule.effect == "deny":
                result.decision = "deny"
                if result.error_code is None or result.error_code == "POLICY_DENIED":
                    result.error_code = rule.error_code or "POLICY_DENIED"
            elif rule.effect == "requires_approval" and result.decision != "deny":
                result.decision = "requires_approval"
        return result


def _format(template: str, scope: dict[str, Any]) -> str:
    """`{po.total_cents}` style placeholders resolved against the facts (best effort)."""
    out = template
    start = 0
    while True:
        i = out.find("{", start)
        if i < 0:
            break
        j = out.find("}", i)
        if j < 0:
            break
        path = out[i + 1 : j]
        value: Any = scope
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else getattr(value, part, None)
            if value is None:
                break
        out = out[:i] + str(value) + out[j + 1 :]
        start = i + len(str(value))
    return out


_engine: PolicyEngine | None = None


def get_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        path = Path(get_settings().policy_path)
        if not path.exists():
            path = _DEFAULT_YAML
        _engine = PolicyEngine.from_file(path)
    return _engine


def set_engine(engine: PolicyEngine | None) -> None:
    global _engine
    _engine = engine
