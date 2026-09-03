"""YAML loading and validation of policy sets."""

from __future__ import annotations

from pathlib import Path

import yaml

from anerp.policy.evaluator import compile_expression
from anerp.policy.rules import PolicySet


def parse_policy_yaml(text: str) -> PolicySet:
    data = yaml.safe_load(text) or {}
    policy = PolicySet.model_validate(data)
    for rule in policy.rules:
        compile_expression(rule.condition)  # raises UnsafeExpression on bad syntax
        for target in rule.applies_to:
            if target.startswith("@") and target[1:] not in policy.groups:
                raise ValueError(f"rule {rule.id}: unknown group {target}")
    return policy


def load_policy_file(path: str | Path) -> PolicySet:
    return parse_policy_yaml(Path(path).read_text())
