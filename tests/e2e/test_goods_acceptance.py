"""Human goods acceptance: parking, deduplication, counts (short/damaged/over), rejection, and
the three-way match against accepted quantities."""

from __future__ import annotations

from tests.conftest import Client, tb_balanced

LINES = [
    {"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"},
    {"sku": "HOSE-10M", "qty": 20, "unit_cost": "25.00"},
]


def _park(agent: Client, po_number: str) -> dict:
    r = agent.commit("receive_goods", po=po_number)
    assert r["error"]["code"] == "REQUIRES_APPROVAL", r
    return r["error"]["details"]


def test_accept_goods_at_counted_quantities(kernel, agent: Client, human: Client) -> None:
    po = agent.ok("create_purchase_order", supplier="ACME", lines=LINES)["document"]["number"]
    details = _park(agent, po)
    request_id = details["approval_request_id"]
    # a retry with a new key joins the same pending request
    again = _park(agent, po)
    assert again["approval_request_id"] == request_id and again["deduplicated"] is True
    req = human.query("list_pending_approvals", kind="goods_acceptance")["pending"][0]
    assert (
        req["kind"] == "goods_acceptance"
        and req["document_number"] == po
        and req["requested_by"] == "agent:test"
    )
    assert req["projected_effects"]["journal_entry"]["total_debit_cents"] == 100000
    # agents cannot accept
    denied = agent.commit("accept_goods", request_id=request_id)
    assert (
        denied["error"]["code"] == "POLICY_DENIED"
        and "human_approval_only" in denied["error"]["details"]["policy"]["rules_triggered"]
    )
    valve_before = agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"]
    hose_before = agent.query("get_inventory", sku="HOSE-10M")["items"][0]["on_hand_qty"]
    inv_before = agent.query("get_account_balance", account_code="1300")["net_cents"]

    sim = human.simulate(
        "accept_goods",
        request_id=request_id,
        accepted_lines=[
            {"sku": "VALVE-2IN", "qty": 8, "damaged_qty": 2, "note": "2 cracked"},
            {"sku": "HOSE-10M", "qty": 25},
        ],
    )
    assert sim["ok"] and sim["policy"]["decision"] == "allow"
    assert {"discrepancy: VALVE-2IN: 2 damaged", "discrepancy: HOSE-10M: 5 over-shipped"} <= set(
        sim["validation"]["warnings"]
    )
    grn = human.ok(
        "accept_goods",
        request_id=request_id,
        accepted_lines=[
            {"sku": "VALVE-2IN", "qty": 8, "damaged_qty": 2, "note": "2 cracked"},
            {"sku": "HOSE-10M", "qty": 25},
        ],
        comment="counted at the dock",
    )
    assert (
        grn["receipt"]["actor_id"] == "human:controller" and grn["receipt"]["on_behalf_of"] is None
    )
    doc = agent.query("get_document", id_or_number=grn["document"]["number"])
    by_sku = {line["sku"]: line for line in doc["lines"]}
    assert by_sku["VALVE-2IN"] | {} == by_sku["VALVE-2IN"]
    assert (
        by_sku["VALVE-2IN"]["expected_qty"],
        by_sku["VALVE-2IN"]["qty"],
        by_sku["VALVE-2IN"]["damaged_qty"],
        by_sku["VALVE-2IN"]["short_qty"],
    ) == (10, 8, 2, 0)
    assert (
        by_sku["HOSE-10M"]["expected_qty"],
        by_sku["HOSE-10M"]["qty"],
        by_sku["HOSE-10M"]["over_qty"],
    ) == (20, 25, 5)
    assert doc["acceptance_request_id"] == request_id
    assert (
        agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"] == valve_before + 8
    )
    assert (
        agent.query("get_inventory", sku="HOSE-10M")["items"][0]["on_hand_qty"] == hose_before + 25
    )
    assert (
        agent.query("get_account_balance", account_code="1300")["net_cents"]
        == inv_before + 8 * 5000 + 25 * 2500
    )
    po_doc = agent.query("get_document", id_or_number=po)
    assert po_doc["status"] == "received"
    assert {line["sku"]: line["received_qty"] for line in po_doc["lines"]} == {
        "VALVE-2IN": 8,
        "HOSE-10M": 25,
    }
    assert (
        po_doc["approval_requests"][0]["status"] == "approved"
        and po_doc["approval_requests"][0]["decided_by"] == "human:controller"
    )
    events = agent.query("poll_events", after_seq=0, types=["goods.accepted", "goods.received"])
    assert {e["type"] for e in events["events"]} >= {"goods.accepted", "goods.received"}

    # three-way match uses accepted quantities: 10 valves invoiced > 8 accepted
    over = agent.commit(
        "post_supplier_invoice",
        po=po,
        supplier_reference="A-1",
        lines=[
            {"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"},
            {"sku": "HOSE-10M", "qty": 25, "unit_cost": "25.00"},
        ],
    )
    assert over["error"]["code"] == "MATCH_VARIANCE_EXCEEDED"
    assert (
        over["error"]["details"]["approval_kind"] == "invoice_variance"
        and over["error"]["details"]["approval_request_id"]
    )
    variance_id = over["error"]["details"]["approval_request_id"]
    dup = agent.commit(
        "post_supplier_invoice",
        po=po,
        supplier_reference="A-1",
        lines=[
            {"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"},
            {"sku": "HOSE-10M", "qty": 25, "unit_cost": "25.00"},
        ],
    )
    assert (
        dup["error"]["details"]["approval_request_id"] == variance_id
        and dup["error"]["details"]["deduplicated"] is True
    )
    assert human.query("list_pending_approvals", kind="invoice_variance")["count"] == 1
    assert (
        agent.query("search_documents", type="SupplierInvoice", party="ACME", status="posted")[
            "count"
        ]
        == 0
    )  # seed only
    ok = agent.ok(
        "post_supplier_invoice",
        po=po,
        supplier_reference="A-1b",
        lines=[
            {"sku": "VALVE-2IN", "qty": 8, "unit_cost": "50.00"},
            {"sku": "HOSE-10M", "qty": 25, "unit_cost": "25.00"},
        ],
    )
    assert (
        ok["document"]["status"] == "posted"
        and ok["effects"]["details"]["three_way_match"]["variance_cents"] == 0
    )
    assert agent.query("get_document", id_or_number=po)["status"] == "invoiced"
    assert (
        human.ok(
            "reject_approval", request_id=variance_id, reason="invoice corrected and re-posted"
        )["document"]["status"]
        == "rejected"
    )
    assert human.query("list_pending_approvals")["count"] == 0
    assert tb_balanced(agent)


def test_reject_goods_and_resubmit(kernel, agent: Client, human: Client) -> None:
    po = agent.ok(
        "create_purchase_order",
        supplier="BOLT",
        lines=[{"sku": "FLANGE-4", "qty": 50, "unit_cost": "15.00"}],
    )["document"]["number"]
    first = _park(agent, po)["approval_request_id"]
    assert (
        agent.commit("reject_goods", request_id=first, reason="x")["error"]["code"]
        == "POLICY_DENIED"
    )
    rejected = human.ok(
        "reject_goods", request_id=first, reason="wrong flanges delivered, refused at the dock"
    )
    assert rejected["document"]["status"] == "rejected" and "goods.rejected" in [
        e["type"] for e in rejected["events_emitted"]
    ]
    assert agent.query("get_document", id_or_number=po)["status"] == "approved"
    assert agent.query("get_inventory", sku="FLANGE-4")["items"][0]["on_hand_qty"] == 100
    events = agent.query("poll_events", after_seq=0, types=["goods.rejected"])["events"]
    assert events[0]["payload"]["requested_by"] == "agent:test"
    second = _park(agent, po)["approval_request_id"]
    assert second != first
    assert human.commit("accept_goods", request_id=first)["error"]["code"] == "PRECONDITION_FAILED"
    grn = human.ok(
        "accept_goods",
        request_id=second,
        accepted_lines=[{"sku": "FLANGE-4", "qty": 30, "note": "20 short, backordered"}],
    )
    assert grn["effects"]["details"]["discrepancies"] == ["FLANGE-4: 20 short"]
    assert agent.query("get_document", id_or_number=po)["status"] == "partially_received"
    assert human.query("list_pending_approvals")["count"] == 0


def test_accept_goods_wrong_kind_and_scope(kernel, agent: Client, human: Client) -> None:
    from anerp.core.dispatch import dispatch
    from anerp.core.envelope import Envelope, Principal
    from tests.conftest import HUMAN

    po = agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "PUMP-SM", "qty": 30, "unit_cost": "400.00"}],
    )
    po_request = po["approval_request"]["id"]  # a po_approval request
    assert (
        human.commit("accept_goods", request_id=po_request)["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    no_receive = Principal(subject="human:ap", kind="human", scopes=["procurement:write", "*:read"])
    r = dispatch(
        Envelope(
            tool="accept_goods", mode="simulate", actor=HUMAN, payload={"request_id": po_request}
        ),
        principal=no_receive,
    )
    assert (
        r["error"]["code"] == "FORBIDDEN"
        and r["error"]["details"]["required_scope"] == "procurement:receive"
    )
