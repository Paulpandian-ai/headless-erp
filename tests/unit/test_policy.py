from __future__ import annotations

import pytest

from anerp.policy.engine import PolicyEngine
from anerp.policy.evaluator import UnsafeExpression, compile_expression, evaluate

YAML = """
version: 7
params: {limit: 100}
groups: {posting: [a, b]}
rules:
  - {id: r1, applies_to: [a], effect: deny, error_code: PERIOD_CLOSED, condition: "period.status == 'closed'", message: "closed {period.code}"}
  - {id: r2, applies_to: ["@posting"], effect: requires_approval, condition: "doc.total > params.limit"}
  - {id: r3, applies_to: ["*"], effect: warn, condition: "doc.total > 50", message: "big"}
  - {id: r4, applies_to: [c], effect: deny, condition: "any(l.v > 2 for l in lines)"}
"""


def test_engine_decisions() -> None:
    e = PolicyEngine.from_yaml(YAML)
    r = e.evaluate(
        "a", {"period": {"status": "closed", "code": "2026-01"}, "doc": {"total": 10}}, {"id": "x"}
    )
    assert (
        r.decision == "deny"
        and r.error_code == "PERIOD_CLOSED"
        and r.reasons == ["r1: closed 2026-01"]
    )
    assert r.rules_evaluated == ["r1", "r2", "r3"]
    r = e.evaluate("b", {"period": {"status": "open"}, "doc": {"total": 500}}, {})
    assert r.decision == "requires_approval" and r.warnings == ["r3: big"]
    r = e.evaluate("z", {"doc": {"total": 1}}, {})
    assert r.decision == "allow" and r.rules_evaluated == ["r3"]
    r = e.evaluate("c", {"lines": [{"v": 1}, {"v": 3}]}, {})
    assert r.decision == "deny" and r.error_code == "POLICY_DENIED"
    r = e.evaluate("c", {"lines": [{"v": 1}]}, {})
    assert r.decision == "allow"
    assert r.policy_version == 7 and r.policy_hash.startswith("sha256:")


def test_missing_facts_never_fire() -> None:
    e = PolicyEngine.from_yaml(YAML)
    assert e.evaluate("a", {}, {}).decision == "allow"


def test_evaluator_safety() -> None:
    for bad in (
        "__import__('os')",
        "lambda: 1",
        "x := 1",
        "open('f')",
        "a.__class__",
        "[1][0].bit_length()",
    ):
        with pytest.raises(UnsafeExpression):
            evaluate(compile_expression(bad), {"a": {}})
    assert evaluate(compile_expression("max(1, 2) + abs(-3)"), {}) == 5
    assert (
        evaluate(compile_expression("a.b[0] == 1 and not c"), {"a": {"b": [1]}, "c": False}) is True
    )
    assert evaluate(compile_expression("missing.x > 1"), {}) is False


def test_default_policy_loads() -> None:
    from anerp.policy.engine import get_engine

    e = get_engine()
    ids = {r.id for r in e.policy.rules}
    assert {
        "period_lock",
        "po_approval_threshold",
        "po_approver_differs",
        "three_way_match_qty",
        "three_way_match_price",
        "customer_credit_limit",
        "stock_available",
        "close_readiness",
        "large_manual_je",
        "human_approval_only",
    } <= ids


def test_update_policy_hot_swaps(kernel, admin) -> None:
    new_yaml = YAML.replace("version: 7", "version: 8")
    r = admin.ok("update_policy", yaml=new_yaml, comment="test")
    assert r["effects"]["details"]["after_hash"].startswith("sha256:")
    from anerp.policy.engine import get_engine

    assert get_engine().policy.version == 8
    bad = admin.commit(
        "update_policy",
        yaml="rules: [{id: x, effect: deny, condition: 'import os'}]",
        comment="bad",
    )
    assert bad["error"]["code"] == "VALIDATION_ERROR"
    assert get_engine().policy.version == 8
