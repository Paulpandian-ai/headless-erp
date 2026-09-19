"""The deterministic resilience experiments double as regression tests (SQLite in memory)."""

from __future__ import annotations

from anerp.eval.resilience.commit_failure import STAGES
from anerp.eval.resilience.commit_failure import run as run_commit_failure
from anerp.eval.resilience.stale_writes import SCENARIOS
from anerp.eval.resilience.stale_writes import run as run_stale_writes
from anerp.eval.resilience.timeout_duplicates import TimeoutInjector, classify


def test_commit_failure_is_all_or_nothing_at_every_stage() -> None:
    result = run_commit_failure()
    applicable = [t for t in result["trials"] if t["applicable"]]
    assert {t["stage"] for t in applicable} == set(STAGES)
    for t in applicable:
        assert t["all_or_nothing"], t
        assert t["tb_balanced_after"], t
        assert t["retry_same_key"] == "applied", t  # a failed commit leaves no idempotency record
        assert t["second_retry"] == "replayed", t
    assert result["all_pass"]


def test_stale_writes_refused_on_treatment_and_silent_on_control() -> None:
    result = run_stale_writes()
    treatment = {t["scenario"]: t for t in result["trials"] if t["arm"] == "treatment"}
    control = {t["scenario"]: t for t in result["trials"] if t["arm"] == "control"}
    assert set(treatment) == set(control) == set(SCENARIOS)
    for scenario in SCENARIOS:
        t = treatment[scenario]
        assert t["commit_with_simulation"] != "applied", t
        assert t["commit_without_simulation"] != "applied", t
        assert t["tb_balanced"]
        assert control[scenario]["posting_correct"] is False, control[scenario]
    assert treatment["stock_consumed"]["commit_with_simulation"] == "STALE_SIMULATION"
    assert treatment["credit_limit_consumed"]["commit_with_simulation"] == "CREDIT_LIMIT_EXCEEDED"


def test_timeout_injector_fires_once_on_an_applied_commit_and_classifies() -> None:
    inj = TimeoutInjector()
    inj.arm()
    args = {"mode": "commit", "idempotency_key": "k1"}
    applied = {"ok": True, "status": "applied", "document": {"number": "PO-1"}}
    assert inj("create_purchase_order", {"mode": "simulate"}, {"ok": True})[
        "ok"
    ]  # simulate untouched
    out = inj("create_purchase_order", args, applied)
    assert out["ok"] is False and out["error"]["code"] == "TIMEOUT"
    assert inj.fired and inj.fired["idempotency_key"] == "k1"
    assert inj("create_purchase_order", args, applied)["ok"]  # fires once
    trace = [
        {
            "name": "create_purchase_order",
            "mode": "commit",
            "idempotency_key": "k1",
            "outcome": "applied",
        },
        {
            "name": "create_purchase_order",
            "mode": "commit",
            "idempotency_key": "k1",
            "outcome": "replayed",
        },
    ]
    assert classify(trace, inj.fired)["behaviour"] == "reused_key"
    trace[1] = {
        "name": "create_purchase_order",
        "mode": "commit",
        "idempotency_key": "k2",
        "outcome": "applied",
    }
    assert classify(trace, inj.fired)["behaviour"] == "new_key_duplicate"
    trace[1] = {"name": "search_documents", "mode": None}
    assert classify(trace, inj.fired)["behaviour"] == "verified_no_retry"
    assert classify(trace[:1], inj.fired)["behaviour"] == "gave_up"
