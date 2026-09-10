"""End-to-end procure-to-pay through the dispatcher, with human goods acceptance."""

from __future__ import annotations

from tests.conftest import Client, tb_balanced


def test_p2p_simple_with_goods_acceptance(kernel, agent: Client, human: Client) -> None:
    cash_before = agent.query("get_account_balance", account_code="1000")["net_cents"]
    inv_before = agent.query("get_account_balance", account_code="1300")["net_cents"]
    stock_before = agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"]

    sim = agent.simulate(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
    )
    assert sim["ok"] and sim["policy"]["decision"] == "allow", sim
    assert sim["projected_effects"]["documents"][0]["number"].endswith("(projected)")
    po = agent.commit(
        "create_purchase_order",
        simulation_id=sim["simulation_id"],
        supplier="ACME",
        lines=[{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
    )
    assert po["ok"] and po["status"] == "applied" and po["document"]["status"] == "approved", po
    po_number = po["document"]["number"]
    assert agent.query("verify_receipt", receipt_id=po["receipt"]["id"])["valid"]

    # agents may simulate a receipt; committing parks a goods_acceptance request for the warehouse
    sim_grn = agent.simulate("receive_goods", po=po_number)
    assert sim_grn["ok"] and sim_grn["policy"]["decision"] == "requires_approval"
    assert (
        "goods_acceptance_by_human" in sim_grn["policy"]["rules_triggered"]
        and sim_grn["would_commit"] is False
    )
    parked = agent.commit("receive_goods", po=po_number)
    assert not parked["ok"] and parked["error"]["code"] == "REQUIRES_APPROVAL"
    details = parked["error"]["details"]
    assert details["approval_kind"] == "goods_acceptance" and details["receipt_id"]
    assert agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"] == stock_before
    assert agent.query("get_document", id_or_number=po_number)["status"] == "approved"
    pending = human.query("list_pending_approvals", kind="goods_acceptance")
    assert pending["count"] == 1 and pending["pending"][0]["document_number"] == po_number

    grn = human.ok(
        "accept_goods", request_id=details["approval_request_id"], comment="counted 10, all good"
    )
    assert grn["document"]["type"] == "GoodsReceipt" and grn["journal_entry"]["number"].startswith(
        "JE-"
    )
    assert grn["receipt"]["actor_id"] == "human:controller"
    assert (
        agent.query("get_account_balance", account_code="1300")["net_cents"] == inv_before + 50000
    )
    assert agent.query("get_account_balance", account_code="1400")["net_cents"] == -50000
    assert (
        agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"]
        == stock_before + 10
    )
    assert human.query("list_pending_approvals")["count"] == 0

    sim_inv = agent.simulate(
        "post_supplier_invoice",
        po=po_number,
        supplier_reference="A-1",
        lines=[{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
    )
    assert (
        sim_inv["ok"]
        and sim_inv["projected_effects"]["details"]["three_way_match"]["variance_cents"] == 0
    )
    sinv = agent.ok(
        "post_supplier_invoice",
        po=po_number,
        supplier_reference="A-1",
        lines=[{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
    )
    assert agent.query("get_account_balance", account_code="1400")["net_cents"] == 0
    assert agent.query("get_account_balance", account_code="2000")["net_cents"] == -50000
    assert agent.query("list_open_items", kind="ap", party="ACME")["total_remaining_cents"] == 50000

    pay = agent.ok("pay_supplier", invoice=sinv["document"]["number"])
    assert pay["effects"]["details"]["remaining_after"] == "0.00"
    assert (
        agent.query("get_account_balance", account_code="1000")["net_cents"] == cash_before - 50000
    )
    assert agent.query("get_document", id_or_number=po_number)["status"] == "invoiced"
    assert tb_balanced(agent)
    trace = agent.query("trace_document", id_or_number=pay["document"]["number"])
    assert [n["type"] for n in trace["nodes"]] == [
        "PurchaseOrder",
        "ApprovalRequest",
        "GoodsReceipt",
        "SupplierInvoice",
        "SupplierPayment",
    ]


def test_human_token_receives_directly(kernel, agent: Client, human: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="BOLT",
        lines=[{"sku": "FLANGE-4", "qty": 20, "unit_cost": "15.00"}],
    )
    sim = human.simulate("receive_goods", po=po["document"]["number"])
    assert sim["policy"]["decision"] == "allow"
    grn = human.ok("receive_goods", po=po["document"]["number"])
    assert (
        grn["document"]["type"] == "GoodsReceipt"
        and grn["effects"]["details"]["discrepancies"] == []
    )
    assert human.query("list_pending_approvals")["count"] == 0
    assert (
        agent.query("get_document", id_or_number=po["document"]["number"])["status"] == "received"
    )
