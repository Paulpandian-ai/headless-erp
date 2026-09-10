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
            lines=[{"sku": "VALVE-2IN", "qty": 1, "unit_cost": "1.00"}],
        )
        assert r["ok"] and r["simulation_id"]
    r = agent.simulate(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "PUMP-SM", "qty": 30, "unit_cost": "400.00"}],
    )
    assert r["policy"]["decision"] == "requires_approval"
    r = agent.simulate(
        "create_purchase_order",
        supplier="NOPE",
        lines=[{"sku": "VALVE-2IN", "qty": 1, "unit_cost": "1.00"}],
    )
    assert not r["ok"] and r["error"]["code"] == "NOT_FOUND"
    kernel.expire_all()
    assert _counts(kernel) == before
    assert _max_seq(kernel) == seq
    assert request_log.query(mode="simulate")[0].outcome == "error"


def test_idempotent_replay_and_conflict(kernel, agent: Client) -> None:
    payload = {"supplier": "ACME", "lines": [{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}]}
    first = agent.commit("create_purchase_order", key="retry-storm-1", **payload)
    second = agent.commit("create_purchase_order", key="retry-storm-1", **payload)
    assert first["status"] == "applied" and second["status"] == "replayed"
    assert first["receipt"] == second["receipt"]
    assert first["document"] == second["document"]
    assert agent.query("search_documents", type="PurchaseOrder", party="ACME")["count"] == 1
    conflict = agent.commit(
        "create_purchase_order",
        key="retry-storm-1",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 3, "unit_cost": "50.00"}],
    )
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    dups = agent.query("find_duplicates", document_type="PurchaseOrder", window_minutes=5)
    assert dups["count"] == 0


def test_stale_simulation(kernel, agent: Client, human: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
    )
    number = po["document"]["number"]
    sim = human.simulate("receive_goods", po=number, lines=[{"sku": "VALVE-2IN", "qty": 1}])
    assert sim["ok"]
    human.ok("receive_goods", po=number, lines=[{"sku": "VALVE-2IN", "qty": 1}])
    stale = human.commit(
        "receive_goods",
        simulation_id=sim["simulation_id"],
        po=number,
        lines=[{"sku": "VALVE-2IN", "qty": 1}],
    )
    assert stale["error"]["code"] == "STALE_SIMULATION"
    assert stale["error"]["details"]["changed"]
    unknown = human.commit(
        "receive_goods", simulation_id="01NOPE", po=number, lines=[{"sku": "VALVE-2IN", "qty": 1}]
    )
    assert unknown["error"]["code"] == "STALE_SIMULATION"

    fresh = human.simulate("receive_goods", po=number, lines=[{"sku": "VALVE-2IN", "qty": 1}])
    assert human.commit(
        "receive_goods",
        simulation_id=fresh["simulation_id"],
        po=number,
        lines=[{"sku": "VALVE-2IN", "qty": 1}],
    )["ok"]


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
        approve["error"]["code"] == "NOT_FOUND"
    )  # scope ok (procurement:*); the seed has no purchase orders
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
        lines=[{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
    )
    replay = agent.query("replay_simulate", receipt_id=po["receipt"]["id"])
    assert replay["current_simulation"]["ok"] and replay["identical"]
    agent.ok("deactivate_supplier", ref="ACME", reason="test")
    replay2 = agent.query("replay_simulate", receipt_id=po["receipt"]["id"])
    assert (
        not replay2["current_simulation"]["ok"]
        and replay2["current_simulation"]["error"]["code"] == "PRECONDITION_FAILED"
    )
    assert agent.query("search_documents", type="PurchaseOrder")["count"] == 1


def test_requires_approval_without_draft_is_deduplicated_receipted_and_idempotent(
    kernel, agent: Client, human: Client
) -> None:
    """A tool with no pending-version hook: nothing of the projection is written, one pending
    ApprovalRequest exists across retries and duplicate submissions, the write is receipted, and
    the same idempotency key replays the same REQUIRES_APPROVAL answer."""
    from pathlib import Path

    from anerp.policy import engine as policy_engine
    from anerp.policy.engine import PolicyEngine

    yaml_text = (
        Path("policies/default.yaml").read_text()
        + """
  - id: large_je_needs_approval
    applies_to: [post_journal_entry]
    effect: requires_approval
    condition: "je.total_debit_cents > 100000"
    message: "manual entries above 1,000.00 need a controller"
"""
    )
    policy_engine.set_engine(PolicyEngine.from_yaml(yaml_text))
    payload = {
        "memo": "big accrual",
        "lines": [
            {"account": "5100", "debit": "5000.00"},
            {"account": "2000", "credit": "5000.00"},
        ],
    }
    before = agent.query("get_account_balance", account_code="5100")["net_cents"]
    first = agent.commit("post_journal_entry", key="je-approval-0001", **payload)
    assert not first["ok"] and first["error"]["code"] == "REQUIRES_APPROVAL"
    details = first["error"]["details"]
    approval_id = details["approval_request_id"]
    assert details["deduplicated"] is False and details["receipt_id"] == first["receipt"]["id"]
    assert agent.query("verify_receipt", receipt_id=details["receipt_id"])["valid"]
    # same key -> replayed, same request; different key, same payload -> deduplicated onto it
    again = agent.commit("post_journal_entry", key="je-approval-0001", **payload)
    assert (
        again["status"] == "replayed"
        and again["error"]["details"]["approval_request_id"] == approval_id
    )
    retry = agent.commit("post_journal_entry", key="je-approval-0002", **payload)
    assert (
        retry["error"]["details"]["approval_request_id"] == approval_id
        and retry["error"]["details"]["deduplicated"] is True
    )
    pending = human.query("list_pending_approvals")
    assert pending["count"] == 1 and pending["pending"][0]["document_id"] is None
    assert (
        pending["pending"][0]["kind"] == "po_approval"
        and pending["pending"][0]["payload"]["memo"] == "big accrual"
    )
    assert (
        pending["pending"][0]["projected_effects"]["journal_entry"]["total_debit_cents"] == 500000
    )
    # nothing of the business projection was written; the request itself is traceable
    assert agent.query("get_account_balance", account_code="5100")["net_cents"] == before
    assert (
        agent.query("search_documents", type="JournalEntry", status="posted")["count"]
        == agent.query("search_documents", type="JournalEntry")["count"]
    )
    trace = agent.query("trace_document", id_or_number=approval_id)
    assert (
        trace["root"]["type"] == "ApprovalRequest"
        and trace["nodes"][0]["receipts"][0]["tool"] == "post_journal_entry"
    )
    events = agent.query("poll_events", after_seq=0, types=["approval.requested"])
    assert events["count"] == 2 and all(e["receipt_id"] for e in events["events"])
    assert human.ok("reject_approval", request_id=approval_id, reason="not now")["ok"]


def test_idempotency_race_returns_replayed(kernel, agent: Client, monkeypatch) -> None:
    """Two commits with the same key that both pass the lookup: the loser hits the primary key
    at commit time and must answer with the winner's stored response, not INTERNAL_ERROR."""
    from anerp.core import dispatch as d

    payload = {"supplier": "ACME", "lines": [{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}]}
    first = agent.commit("create_purchase_order", key="race-key-0001", **payload)
    assert first["status"] == "applied"
    count = agent.query("search_documents", type="PurchaseOrder")["count"]
    monkeypatch.setattr(
        d.idempotency, "lookup", lambda session, key: None
    )  # both "pass" the lookup
    second = agent.commit("create_purchase_order", key="race-key-0001", **payload)
    assert second["ok"] and second["status"] == "replayed"
    assert second["document"] == first["document"] and second["receipt"] == first["receipt"]
    assert agent.query("search_documents", type="PurchaseOrder")["count"] == count
    conflict = agent.commit(
        "create_purchase_order",
        key="race-key-0001",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 3, "unit_cost": "50.00"}],
    )
    assert (
        conflict["error"]["code"] == "INTERNAL_ERROR"
    )  # different payload racing the same key: nothing applied
    assert agent.query("search_documents", type="PurchaseOrder")["count"] == count


def test_principal_required_outside_test_env(kernel, agent: Client, monkeypatch) -> None:
    from anerp.config import get_settings
    from anerp.core.envelope import local_principal
    from anerp.mcp_server.registry import call_tool

    monkeypatch.setattr(get_settings(), "env", "dev")
    for tool_name, payload in (
        ("approve_purchase_order", {"po": "PO-000001"}),
        ("receive_goods", {"po": "PO-000001"}),
        ("create_supplier", {"code": "Q", "name": "Q"}),
    ):
        r = dispatch(
            Envelope(
                tool=tool_name,
                mode="simulate",
                actor=Actor(id="human:forged", kind="human"),
                payload=payload,
            )
        )
        assert r["error"]["code"] == "UNAUTHORIZED", tool_name
    assert run_query("get_trial_balance", {}, AGENT)["error"]["code"] == "UNAUTHORIZED"
    assert call_tool("get_trial_balance", {}, None)["error"]["code"] == "UNAUTHORIZED"
    ok = dispatch(
        Envelope(
            tool="create_supplier", mode="simulate", actor=AGENT, payload={"code": "Q", "name": "Q"}
        ),
        principal=local_principal("human:cli"),
    )
    assert ok["ok"]
    assert run_query("get_trial_balance", {}, AGENT, principal=local_principal())["ok"]


def test_internal_error_message_is_generic(kernel, agent: Client, monkeypatch) -> None:
    from anerp.core.registry import registry

    tool = registry.get("create_supplier")

    def boom(ctx, payload):
        raise RuntimeError("SELECT secret FROM customers -- leaked detail")

    monkeypatch.setattr(tool, "project", boom)
    r = agent.commit("create_supplier", code="X", name="X")
    assert r["error"]["code"] == "INTERNAL_ERROR"
    assert "leaked" not in r["error"]["message"] and r["request_id"] in r["error"]["message"]
