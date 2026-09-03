"""End-to-end procure-to-pay through the dispatcher."""

from __future__ import annotations

from tests.conftest import Client, tb_balanced


def test_p2p_simple(kernel, agent: Client) -> None:
    cash_before = agent.query("get_account_balance", account_code="1000")["net_cents"]
    inv_before = agent.query("get_account_balance", account_code="1300")["net_cents"]

    sim = agent.simulate(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
    )
    assert sim["ok"] and sim["policy"]["decision"] == "allow", sim
    assert sim["projected_effects"]["documents"][0]["number"].endswith("(projected)")
    po = agent.commit(
        "create_purchase_order",
        simulation_id=sim["simulation_id"],
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
    )
    assert po["ok"] and po["status"] == "applied", po
    assert po["document"]["status"] == "approved"
    po_number = po["document"]["number"]
    assert po_number.startswith("PO-")
    assert po["receipt"]["signature"]
    assert agent.query("verify_receipt", receipt_id=po["receipt"]["id"])["valid"]

    grn = agent.ok("receive_goods", po=po_number)
    assert grn["journal_entry"]["number"].startswith("JE-")
    assert (
        agent.query("get_account_balance", account_code="1300")["net_cents"] == inv_before + 50000
    )
    assert agent.query("get_account_balance", account_code="1400")["net_cents"] == -50000

    sim_inv = agent.simulate(
        "post_supplier_invoice",
        po=po_number,
        supplier_reference="A-1",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
    )
    assert (
        sim_inv["ok"]
        and sim_inv["projected_effects"]["details"]["three_way_match"]["variance_cents"] == 0
    )
    sinv = agent.ok(
        "post_supplier_invoice",
        po=po_number,
        supplier_reference="A-1",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
    )
    assert sinv["document"]["status"] == "posted"
    assert agent.query("get_account_balance", account_code="1400")["net_cents"] == 0
    assert agent.query("get_account_balance", account_code="2000")["net_cents"] == -50000
    open_items = agent.query("list_open_items", kind="ap", party="ACME")
    assert open_items["total_remaining_cents"] == 50000

    pay = agent.ok("pay_supplier", invoice=sinv["document"]["number"])
    assert pay["effects"]["details"]["remaining_after"] == "0.00"
    assert agent.query("get_account_balance", account_code="2000")["net_cents"] == 0
    assert (
        agent.query("get_account_balance", account_code="1000")["net_cents"] == cash_before - 50000
    )
    assert agent.query("list_open_items", kind="ap", party="ACME")["count"] == 0
    doc = agent.query("get_document", id_or_number=po_number)
    assert doc["status"] == "invoiced"
    assert tb_balanced(agent)

    trace = agent.query("trace_document", id_or_number=pay["document"]["number"])
    types = [n["type"] for n in trace["nodes"]]
    assert types == ["PurchaseOrder", "GoodsReceipt", "SupplierInvoice", "SupplierPayment"]
