"""The baseline fixture and reset_and_seed: periods, opening entries, atomicity, idempotency,
and final document numbers in committed artifacts."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from anerp.core.requestlog import request_log
from anerp.seed import CLOSED_PERIOD, ITEMS, OPEN_PERIOD
from tests.conftest import Client


def test_baseline_periods(kernel, agent: Client) -> None:
    assert agent.query("get_period", period_code=CLOSED_PERIOD)["period"]["status"] == "closed"
    assert agent.query("get_period", period_code=OPEN_PERIOD)["period"]["status"] == "open"
    today = date.today().strftime("%Y-%m")
    if today != CLOSED_PERIOD:
        assert agent.query("get_period", period_code=today)["period"]["status"] == "open"
    events = agent.query("poll_events", after_seq=0, types=["period.closed"])["events"]
    assert [e["payload"]["summary"] for e in events] == [
        f"Period {CLOSED_PERIOD} closed by system:seed"
    ]


def test_baseline_opening_stock_is_an_opening_entry(kernel, agent: Client) -> None:
    expected_value = sum(
        int(round(float(cost) * 100)) * on_hand for _, _, cost, _, on_hand in ITEMS
    )
    assert expected_value == 275000
    assert agent.query("search_documents", type="PurchaseOrder")["count"] == 0
    assert agent.query("search_documents", type="GoodsReceipt")["count"] == 0
    assert agent.query("search_documents", type="SupplierInvoice")["count"] == 0
    assert agent.query("list_open_items", kind="ap")["count"] == 0
    assert agent.query("get_account_balance", account_code="1400")["net_cents"] == 0
    assert agent.query("get_account_balance", account_code="1300")["net_cents"] == expected_value
    assert agent.query("get_account_balance", account_code="1000")["net_cents"] == 25_000_000
    assert agent.query("get_account_balance", account_code="3000")["net_cents"] == -(
        25_000_000 + expected_value
    )
    inventory = {i["sku"]: i["on_hand_qty"] for i in agent.query("get_inventory")["items"]}
    assert inventory == {sku: on_hand for sku, _, _, _, on_hand in ITEMS}
    recon = agent.query("get_reconciliation", kind="inventory")
    assert recon["reconciled"] and recon["subledger_value_cents"] == expected_value
    gr_ir = agent.query("get_reconciliation", kind="gr_ir")
    assert gr_ir["reconciled"] and gr_ir["subledger_open_cents"] == 0
    opening = [j for j in agent.query("search_documents", type="JournalEntry", limit=50)["items"]]
    memos = {agent.query("get_document", id_or_number=j["number"])["memo"] for j in opening}
    assert any(m.startswith("Opening stock") for m in memos) and "Opening capital" in memos
    assert agent.query("get_trial_balance")["is_balanced"]


def test_create_item_opening_qty_rules(kernel, agent: Client) -> None:
    r = agent.commit(
        "create_item",
        sku="SVC-1",
        name="svc",
        is_stocked=False,
        opening_qty=3,
        standard_cost="1.00",
    )
    assert r["error"]["code"] == "PRECONDITION_FAILED"
    r = agent.commit("create_item", sku="FREE-1", name="free", standard_cost="0.00", opening_qty=3)
    assert r["error"]["code"] == "PRECONDITION_FAILED"
    closed = agent.commit(
        "create_item",
        sku="OLD-1",
        name="old",
        standard_cost="2.00",
        opening_qty=3,
        opening_date=f"{CLOSED_PERIOD}-15",
    )
    assert closed["error"]["code"] == "PERIOD_CLOSED"
    ok = agent.ok(
        "create_item",
        sku="NEW-1",
        name="new",
        standard_cost="2.00",
        list_price="3.00",
        opening_qty=3,
    )
    assert ok["journal_entry"] and ok["effects"]["details"]["opening_value_cents"] == 600
    assert agent.query("get_inventory", sku="NEW-1")["items"][0]["on_hand_qty"] == 3


def _counts(session) -> dict[str, int]:
    return {
        t: session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        for t in ("supplier", "item", "journal_entry", "event", "receipt", "idempotency_record")
    }


def test_reset_and_seed_is_atomic(kernel, admin: Client, agent: Client, monkeypatch) -> None:
    import anerp.seed as seed_module

    marker = agent.ok("create_supplier", code="MARKER", name="survives a failed reset")
    before = _counts(kernel)
    real = seed_module.seed_fixture

    def broken(session, name="baseline", actor_id="system:seed"):
        real(session, name, actor_id)  # everything is applied, then the tail fails
        raise RuntimeError("simulated failure at the tail of the fixture")

    monkeypatch.setattr(seed_module, "seed_fixture", broken)
    failed = admin.commit(
        "reset_and_seed", key="reset-atomic-0001", fixture_name="baseline", confirm="RESET"
    )
    assert failed["error"]["code"] == "INTERNAL_ERROR"
    kernel.expire_all()
    assert _counts(kernel) == before  # nothing wiped, nothing re-seeded
    assert agent.query("get_document", id_or_number=marker["document"]["id"])["code"] == "MARKER"
    assert agent.query("poll_events", after_seq=0, types=["system.reset"])["count"] == 0

    monkeypatch.setattr(seed_module, "seed_fixture", real)
    ok = admin.commit(
        "reset_and_seed", key="reset-atomic-0002", fixture_name="baseline", confirm="RESET"
    )
    assert ok["ok"] and ok["hook_result"]["fixture"] == "baseline"
    events = agent.query("poll_events", after_seq=0)["events"]
    assert events[-1]["type"] == "system.reset" and events[-1]["receipt_id"] == ok["receipt"]["id"]
    assert agent.query("verify_receipt", receipt_id=ok["receipt"]["id"])["valid"]
    assert agent.query("search_documents", type="Supplier")["count"] == 2  # MARKER is gone
    assert agent.query("get_period", period_code=CLOSED_PERIOD)["period"]["status"] == "closed"

    # replaying the same key must not wipe again
    after = agent.ok("create_supplier", code="AFTER", name="created after the reset")
    replay = admin.commit(
        "reset_and_seed", key="reset-atomic-0002", fixture_name="baseline", confirm="RESET"
    )
    assert replay["ok"] and replay["status"] == "replayed"
    assert agent.query("get_document", id_or_number=after["document"]["id"])["code"] == "AFTER"
    assert request_log.query(tool="reset_and_seed")[0].outcome == "replayed"


def test_committed_artifacts_carry_final_numbers(kernel, agent: Client, human: Client) -> None:
    """Numbers are allocated during projection in commit mode, so nothing derived from a document
    number is left as `... (projected)` (the Postgres VARCHAR(16) failure on Railway)."""
    sim = agent.simulate(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
    )
    assert sim["projected_effects"]["documents"][0]["number"].endswith("(projected)")
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
    )
    assert "(projected)" not in str(po)
    grn = human.ok("receive_goods", po=po["document"]["number"])
    assert "(projected)" not in str(grn)
    je = agent.query("get_document", id_or_number=grn["journal_entry"]["number"])
    assert grn["document"]["number"] in je["memo"] and "(projected)" not in je["memo"]
    inv = agent.ok(
        "post_supplier_invoice",
        po=po["document"]["number"],
        supplier_reference="N1",
        lines=[{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}],
    )
    open_item = agent.query("list_open_items", kind="ap", party="ACME")["items"][0]
    assert (
        open_item["source_doc_number"] == inv["document"]["number"]
        and len(open_item["source_doc_number"]) <= 16
    )
    events = agent.query("poll_events", after_seq=0)["events"]
    assert not any("(projected)" in e["payload"]["summary"] for e in events)
    assert "(projected)" not in str(inv["compensating_tool"])
    # a failed commit rolls the allocation back: the next number is not skipped
    bad = agent.commit(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "NOPE", "qty": 1, "unit_cost": "1.00"}],
    )
    assert bad["error"]["code"] == "NOT_FOUND"
    nxt = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 1, "unit_cost": "50.00"}],
    )
    assert (
        int(nxt["document"]["number"].split("-")[1])
        == int(po["document"]["number"].split("-")[1]) + 1
    )
