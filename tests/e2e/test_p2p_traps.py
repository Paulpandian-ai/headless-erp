"""Procurement traps: approval threshold, price variance, reversals, cancellation."""

from __future__ import annotations

from tests.conftest import ADMIN, Client, tb_balanced


def test_over_threshold_requires_human_approval(kernel, agent: Client, human: Client) -> None:
    sim = agent.simulate(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "GADGET-2", "qty": 125, "unit_cost": "120.00"}],
    )
    assert sim["policy"]["decision"] == "requires_approval"
    assert "po_approval_threshold" in sim["policy"]["rules_triggered"]
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "GADGET-2", "qty": 125, "unit_cost": "120.00"}],
    )
    assert po["document"]["status"] == "draft"
    assert po["approval_request"]["status"] == "pending"
    assert "approval.requested" in [e["type"] for e in po["events_emitted"]]
    number = po["document"]["number"]
    blocked = agent.commit("receive_goods", po=number)
    assert blocked["error"]["code"] == "PRECONDITION_FAILED"
    # agent tokens cannot approve
    denied = agent.commit("approve_purchase_order", po=number)
    assert (
        denied["error"]["code"] == "POLICY_DENIED"
        and "human_approval_only" in denied["error"]["details"]["policy"]["rules_triggered"]
    )
    pending = human.query("list_pending_approvals")
    assert pending["count"] == 1 and pending["pending"][0]["document_number"] == number
    # the creator cannot approve their own PO even as a human
    self_approve = Client(type(ADMIN)(id="agent:test", kind="human")).commit(
        "approve_purchase_order", po=number
    )
    assert (
        self_approve["error"]["code"] == "POLICY_DENIED"
        and "po_approver_differs" in self_approve["error"]["details"]["policy"]["rules_triggered"]
    )
    approved = human.ok("approve_purchase_order", po=number, comment="ok")
    assert approved["document"]["status"] == "approved"
    assert human.query("list_pending_approvals")["count"] == 0
    assert agent.ok("receive_goods", po=number)["ok"]
    assert tb_balanced(agent)


def test_reject_approval(kernel, agent: Client, human: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "GADGET-2", "qty": 200, "unit_cost": "120.00"}],
    )
    req_id = po["approval_request"]["id"]
    rejected = human.ok("reject_approval", request_id=req_id, reason="budget")
    assert rejected["document"]["status"] == "rejected"
    events = agent.query("poll_events", after_seq=0, types=["approval.rejected"])
    assert events["count"] == 1 and events["events"][0]["payload"]["requested_by"] == "agent:test"
    assert (
        agent.ok("cancel_purchase_order", po=po["document"]["number"], reason="rejected")[
            "document"
        ]["status"]
        == "cancelled"
    )


def test_price_variance_within_and_outside_tolerance(kernel, agent: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
    )
    number = po["document"]["number"]
    agent.ok("receive_goods", po=number)
    # 5% above -> blocked
    sim = agent.simulate(
        "post_supplier_invoice",
        po=number,
        supplier_reference="V1",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "52.50"}],
    )
    assert (
        sim["policy"]["decision"] == "deny"
        and sim["commit_would_fail_with"] == "MATCH_VARIANCE_EXCEEDED"
    )
    assert sim["projected_effects"]["details"]["three_way_match"]["variance_cents"] == 2500
    res = agent.commit(
        "post_supplier_invoice",
        po=number,
        supplier_reference="V1",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "52.50"}],
    )
    assert res["error"]["code"] == "MATCH_VARIANCE_EXCEEDED"
    # 1% above -> within tolerance, variance to 5200
    ok = agent.ok(
        "post_supplier_invoice",
        po=number,
        supplier_reference="V2",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.50"}],
    )
    assert ok["document"]["status"] == "posted"
    assert any("within tolerance" in w for w in ok["warnings"])
    assert agent.query("get_account_balance", account_code="5200")["net_cents"] == 500
    assert agent.query("get_account_balance", account_code="2000")["net_cents"] == -50500
    doc = agent.query("get_document", id_or_number=ok["document"]["number"])
    assert doc["match_status"] == "variance_within_tolerance"
    # qty over receipt -> blocked
    over = agent.commit(
        "post_supplier_invoice",
        po=number,
        supplier_reference="V3",
        lines=[{"sku": "WIDGET-1", "qty": 1, "unit_cost": "50.00"}],
    )
    assert over["error"]["code"] == "MATCH_VARIANCE_EXCEEDED"
    assert tb_balanced(agent)


def test_parked_invoice_blocks_close(kernel, agent: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
    )
    number = po["document"]["number"]
    agent.ok("receive_goods", po=number)
    parked = agent.ok(
        "post_supplier_invoice",
        po=number,
        supplier_reference="P1",
        lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "60.00"}],
        park_if_blocked=True,
    )
    assert parked["document"]["status"] == "blocked" and parked["journal_entry"] is None
    period = parked["effects"]["documents"][0]["fields"]["posting_date"][:7]
    readiness = agent.query("get_period", period_code=period)["close_readiness"]
    assert not readiness["ready"] and readiness["blocked_supplier_invoices"] == [
        parked["document"]["number"]
    ]
    close = agent.commit("close_period", period=period)
    assert (
        close["error"]["code"] == "POLICY_DENIED"
        and "close_readiness" in close["error"]["details"]["policy"]["rules_triggered"]
    )
    agent.ok("reverse_supplier_invoice", invoice=parked["document"]["number"], reason="wrong price")
    assert agent.query("get_period", period_code=period)["close_readiness"]["ready"]


def test_p2p_reversals(kernel, agent: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="NORTHWIND",
        lines=[{"sku": "BOLT-3", "qty": 100, "unit_cost": "1.00"}],
    )
    number = po["document"]["number"]
    grn = agent.ok("receive_goods", po=number, lines=[{"sku": "BOLT-3", "qty": 40}])
    assert agent.query("get_document", id_or_number=number)["status"] == "partially_received"
    rev = agent.ok("reverse_goods_receipt", grn=grn["document"]["number"], reason="wrong delivery")
    assert rev["document"]["type"] == "GoodsReceipt" and rev["journal_entry"]
    assert agent.query("get_document", id_or_number=number)["status"] == "approved"
    assert agent.query("get_account_balance", account_code="1400")["net_cents"] == 0
    grn2 = agent.ok("receive_goods", po=number)
    sinv = agent.ok(
        "post_supplier_invoice",
        po=number,
        supplier_reference="N1",
        lines=[{"sku": "BOLT-3", "qty": 100, "unit_cost": "1.00"}],
    )
    assert (
        agent.commit("reverse_goods_receipt", grn=grn2["document"]["number"], reason="x")["error"][
            "code"
        ]
        == "PRECONDITION_FAILED"
    )
    pay = agent.ok("pay_supplier", invoice=sinv["document"]["number"], amount="40.00")
    assert (
        agent.commit("reverse_supplier_invoice", invoice=sinv["document"]["number"], reason="x")[
            "error"
        ]["code"]
        == "PRECONDITION_FAILED"
    )
    agent.ok("reverse_supplier_payment", payment=pay["document"]["number"], reason="bounced")
    assert (
        agent.query("list_open_items", kind="ap", party="NORTHWIND")["total_remaining_cents"]
        == 10000
    )
    agent.ok("reverse_supplier_invoice", invoice=sinv["document"]["number"], reason="re-post")
    assert agent.query("get_document", id_or_number=number)["status"] == "received"
    assert agent.query("list_open_items", kind="ap", party="NORTHWIND")["count"] == 0
    assert tb_balanced(agent)
    recon = agent.query("get_reconciliation", kind="gr_ir")
    assert recon["reconciled"] and recon["subledger_open_cents"] == 10000
    assert agent.query("get_reconciliation", kind="ap")["reconciled"]
    assert agent.query("get_reconciliation", kind="inventory")["reconciled"]
    cancel = agent.commit("cancel_purchase_order", po=number, reason="x")
    assert cancel["error"]["code"] == "PRECONDITION_FAILED"
    assert grn2["document"]["number"] in cancel["error"]["details"]["blocking_documents"]
