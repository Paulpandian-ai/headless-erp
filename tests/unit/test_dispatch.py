"""Dispatcher invariants: simulate writes nothing, idempotency, stale simulation, scopes."""

from __future__ import annotations

from sqlalchemy import text

from anerp.core.dispatch import dispatch, run_query
from anerp.core.envelope import Actor, Envelope, Principal
from anerp.core.requestlog import request_log
from tests.conftest import AGENT, Client

TABLES = [
    "purchase_order",
    "purchase_order_line",
    "journal_entry",
    "journal_line",
    "event",
    "receipt",
    "idempotency_record",
    "approval_request",
    "open_item",
    "document_sequence",
]


def _counts(session) -> dict[str, int]:
    return {t: session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in TABLES}


def _max_seq(session) -> int:
    return session.execute(text("SELECT COALESCE(MAX(seq),0) FROM event")).scalar()


def test_simulate_writes_nothing(kernel, agent: Client) -> None:
    before = _counts(kernel)
    seq = _max_seq(kernel)
    for _ in range(3):
        r = agent.simulate(
            "create_purchase_order",
            supplier="ACME",
            lines=[{"sku": "WIDGET-1", "qty": 1, "unit_cost": "1.00"}],
        )
        assert r["ok"] and r["simulation_id"]
    r = agent.simulate(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "GADGET-2", "qty": 200, "unit_cost": "120.00"}],
    )
    assert r["policy"]["decision"] == "requires_approval"
    r = agent.simulate(
        "create_purchase_order",
        supplier="NOPE",
        lines=[{"sku": "WIDGET-1", "qty": 1, "unit_cost": "1.00"}],
    )
    assert not r["ok"] and r["error"]["code"] == "NOT_FOUND"
    kernel.expire_all()
    assert _counts(kernel) == before
    assert _max_seq(kernel) == seq
    assert request_log.query(mode="simulate")[0].outcome == "error"


def test_idempotent_replay_and_conflict(kernel, agent: Client) -> None:
    payload = {"supplier": "ACME", "lines": [{"sku": "WIDGET-1", "qty": 2, "unit_cost": "50.00"}]}
    first = agent.commit("create_purchase_order", key="retry-storm-1", **payload)
    second = agent.commit("create_purchase_order", key="retry-storm-1", **payload)
    assert first["status"] == "applied" and second["status"] == "replayed"
    assert first["receipt"] == second["receipt"]
    assert first["document"] == second["document"]
    assert (
        agent.query("search_documents", type="PurchaseOrder", party="ACME")["count"] == 2
    )  # seed PO + this one
    conflict = agent.commit(
        "create_purchase_order",
        key="retry-storm-1",
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 3, "unit_cost": "50.00"}],
    )
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    dups = agent.query("find_duplicates", document_type="PurchaseOrder", window_minutes=5)
    assert dups["count"] == 0


def test_stale_simulation(kernel, agent: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 2, "unit_cost": "50.00"}],
    )
    number = po["document"]["number"]
    sim = agent.simulate("receive_goods", po=number, lines=[{"sku": "WIDGET-1", "qty": 1}])
    assert sim["ok"]
    agent.ok("receive_goods", po=number, lines=[{"sku": "WIDGET-1", "qty": 1}])
    stale = agent.commit(
        "receive_goods",
        simulation_id=sim["simulation_id"],
        po=number,
        lines=[{"sku": "WIDGET-1", "qty": 1}],
    )
    assert stale["error"]["code"] == "STALE_SIMULATION"
    assert stale["error"]["details"]["changed"]
    fresh = agent.simulate("receive_goods", po=number, lines=[{"sku": "WIDGET-1", "qty": 1}])
    assert agent.commit(
        "receive_goods",
        simulation_id=fresh["simulation_id"],
        po=number,
        lines=[{"sku": "WIDGET-1", "qty": 1}],
    )["ok"]
    unknown = agent.commit(
        "receive_goods", simulation_id="01NOPE", po=number, lines=[{"sku": "WIDGET-1", "qty": 1}]
    )
    assert unknown["error"]["code"] == "STALE_SIMULATION"


def test_envelope_validation(kernel) -> None:
    r = dispatch({"tool": "create_supplier", "mode": "commit", "actor": {"id": "x"}, "payload": {}})
    assert r["error"]["code"] == "VALIDATION_ERROR"
    r = dispatch(Envelope(tool="nope", mode="simulate", actor=AGENT, payload={}))
    assert r["error"]["code"] == "VALIDATION_ERROR"
    r = dispatch(
        Envelope(tool="create_supplier", mode="simulate", actor=AGENT, payload={"code": "X"})
    )
    assert r["error"]["code"] == "VALIDATION_ERROR" and r["error"]["details"]["errors"]
    r = run_query("get_document", {"id_or_number": "PO-999999"}, AGENT)
    assert r["error"]["code"] == "NOT_FOUND"


def test_scope_enforcement(kernel) -> None:
    reader = Principal(subject="agent:reader", kind="agent", scopes=["*:read"])
    r = dispatch(
        Envelope(
            tool="create_supplier", mode="simulate", actor=AGENT, payload={"code": "Z", "name": "Z"}
        ),
        principal=reader,
    )
    assert r["error"]["code"] == "FORBIDDEN"
    assert run_query("get_trial_balance", {}, AGENT, principal=reader)["ok"]
    assert run_query("list_tokens", {}, AGENT, principal=reader)["error"]["code"] == "FORBIDDEN"
    writer = Principal(
        subject="agent:writer", kind="agent", scopes=["masterdata:write", "procurement:*"]
    )
    r = dispatch(
        Envelope(
            tool="create_supplier",
            mode="commit",
            idempotency_key="scope-test-1",
            actor=Actor(id="ignored", kind="human", on_behalf_of="human:bob"),
            payload={"code": "Z", "name": "Z"},
        ),
        principal=writer,
    )
    assert (
        r["ok"]
        and r["receipt"]["actor_id"] == "agent:writer"
        and r["receipt"]["on_behalf_of"] == "human:bob"
    )
    approve = dispatch(
        Envelope(
            tool="approve_purchase_order", mode="simulate", actor=AGENT, payload={"po": "PO-000001"}
        ),
        principal=writer,
    )
    assert (
        approve["error"]["code"] == "PRECONDITION_FAILED"
    )  # scope ok (procurement:*), PO already invoiced
    admin = Principal(subject="admin:x", kind="admin", scopes=["admin:*"])
    assert run_query("list_tokens", {}, AGENT, principal=admin)["ok"]


def test_explain_error_and_request_log(kernel, agent: Client) -> None:
    r = agent.commit("ship_order", so="SO-999999")
    explained = agent.query("explain_error", request_id=r["request_id"])
    assert explained["error_code"] == "NOT_FOUND" and "NOT_FOUND" in explained["explanation"]
    log = agent.query("get_request_log", tool="ship_order", error_code="NOT_FOUND")
    assert log["count"] == 1
    activity = agent.query("get_agent_activity", actor_id="agent:test")
    assert activity["error_codes"]["NOT_FOUND"] == 1


def test_replay_simulate(kernel, agent: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 2, "unit_cost": "50.00"}],
    )
    replay = agent.query("replay_simulate", receipt_id=po["receipt"]["id"])
    assert replay["current_simulation"]["ok"] and replay["identical"]
    agent.ok("deactivate_supplier", ref="ACME", reason="test")
    replay2 = agent.query("replay_simulate", receipt_id=po["receipt"]["id"])
    assert (
        not replay2["current_simulation"]["ok"]
        and replay2["current_simulation"]["error"]["code"] == "PRECONDITION_FAILED"
    )
    assert agent.query("search_documents", type="PurchaseOrder")["count"] == 2
