"""End-to-end order-to-cash with credit-limit and stock traps."""

from __future__ import annotations

from tests.conftest import Client, tb_balanced


def test_o2c_simple(kernel, agent: Client) -> None:
    so = agent.ok("create_sales_order", customer="GLOBEX", lines=[{"sku": "WIDGET-1", "qty": 5}])
    assert so["document"]["status"] == "open"
    assert so["effects"]["details"]["total"] == "400.00"
    so_number = so["document"]["number"]
    inv_before = agent.query("get_inventory", sku="WIDGET-1")["items"][0]["on_hand_qty"]

    shp = agent.ok("ship_order", so=so_number)
    assert shp["effects"]["details"]["cogs"] == "250.00"
    assert agent.query("get_inventory", sku="WIDGET-1")["items"][0]["on_hand_qty"] == inv_before - 5
    assert agent.query("get_document", id_or_number=so_number)["status"] == "shipped"

    cinv = agent.ok("issue_customer_invoice", so=so_number)
    assert cinv["effects"]["details"]["total"] == "400.00"
    assert (
        agent.query("list_open_items", kind="ar", party="GLOBEX")["total_remaining_cents"] == 40000
    )
    assert agent.query("get_account_balance", account_code="4000")["net_cents"] == -40000

    rcpt = agent.ok("record_customer_payment", invoice=cinv["document"]["number"], amount="150.00")
    assert rcpt["effects"]["details"]["remaining_after"] == "250.00"
    rcpt2 = agent.ok("record_customer_payment", invoice=cinv["document"]["number"])
    assert rcpt2["effects"]["details"]["remaining_after"] == "0.00"
    assert agent.query("get_document", id_or_number=cinv["document"]["number"])["status"] == "paid"
    assert agent.query("get_document", id_or_number=so_number)["status"] == "invoiced"
    assert tb_balanced(agent)
    trace = agent.query("trace_document", id_or_number=so_number)
    assert [n["type"] for n in trace["nodes"]] == [
        "SalesOrder",
        "Shipment",
        "CustomerInvoice",
        "CustomerPayment",
        "CustomerPayment",
    ]


def test_credit_limit_trap(kernel, agent: Client) -> None:
    # INITECH has a 5,000.00 limit; 30 gadgets at 200.00 = 6,000.00
    sim = agent.simulate(
        "create_sales_order", customer="INITECH", lines=[{"sku": "GADGET-2", "qty": 30}]
    )
    assert sim["ok"] and sim["policy"]["decision"] == "deny"
    assert sim["commit_would_fail_with"] == "CREDIT_LIMIT_EXCEEDED"
    assert sim["projected_effects"]["details"]["credit_check"]["exposure_after_cents"] == 600000
    res = agent.commit(
        "create_sales_order", customer="INITECH", lines=[{"sku": "GADGET-2", "qty": 30}]
    )
    assert not res["ok"] and res["error"]["code"] == "CREDIT_LIMIT_EXCEEDED"
    assert agent.query("search_documents", type="SalesOrder", party="INITECH")["count"] == 0
    ok = agent.ok("create_sales_order", customer="INITECH", lines=[{"sku": "GADGET-2", "qty": 20}])
    assert ok["document"]["status"] == "open"


def test_out_of_stock_trap(kernel, agent: Client) -> None:
    on_hand = agent.query("get_inventory", sku="GADGET-2")["items"][0]["on_hand_qty"]
    so = agent.ok(
        "create_sales_order",
        customer="GLOBEX",
        lines=[{"sku": "GADGET-2", "qty": on_hand + 5, "unit_price": "10.00"}],
    )
    sim = agent.simulate("ship_order", so=so["document"]["number"])
    assert (
        sim["policy"]["decision"] == "deny"
        and sim["commit_would_fail_with"] == "INSUFFICIENT_STOCK"
    )
    res = agent.commit("ship_order", so=so["document"]["number"])
    assert res["error"]["code"] == "INSUFFICIENT_STOCK"
    partial = agent.ok(
        "ship_order", so=so["document"]["number"], lines=[{"sku": "GADGET-2", "qty": on_hand}]
    )
    assert partial["document"]["status"] == "posted"
    assert (
        agent.query("get_document", id_or_number=so["document"]["number"])["status"]
        == "partially_shipped"
    )
    assert agent.query("get_inventory", sku="GADGET-2")["items"][0]["on_hand_qty"] == 0


def test_o2c_reversals_and_credit_note(kernel, agent: Client) -> None:
    so = agent.ok("create_sales_order", customer="GLOBEX", lines=[{"sku": "WIDGET-1", "qty": 4}])
    shp = agent.ok("ship_order", so=so["document"]["number"])
    before = agent.query("get_inventory", sku="WIDGET-1")["items"][0]["on_hand_qty"]
    rev = agent.ok("reverse_shipment", shipment=shp["document"]["number"], reason="returned")
    assert rev["journal_entry"]
    assert agent.query("get_inventory", sku="WIDGET-1")["items"][0]["on_hand_qty"] == before + 4
    assert agent.query("get_document", id_or_number=so["document"]["number"])["status"] == "open"
    shp2 = agent.ok("ship_order", so=so["document"]["number"])
    cinv = agent.ok("issue_customer_invoice", so=so["document"]["number"])
    bad = agent.commit("reverse_shipment", shipment=shp2["document"]["number"], reason="too late")
    assert bad["error"]["code"] == "PRECONDITION_FAILED"
    cn = agent.ok(
        "issue_credit_note",
        invoice=cinv["document"]["number"],
        amount="80.00",
        reason="one damaged",
    )
    assert cn["journal_entry"]
    assert (
        agent.query("list_open_items", kind="ar", party="GLOBEX")["total_remaining_cents"] == 24000
    )
    pay = agent.ok("record_customer_payment", invoice=cinv["document"]["number"])
    revpay = agent.ok(
        "reverse_customer_payment", payment=pay["document"]["number"], reason="bounced"
    )
    assert revpay["ok"]
    assert (
        agent.query("list_open_items", kind="ar", party="GLOBEX")["total_remaining_cents"] == 24000
    )
    assert tb_balanced(agent)
    cancel = agent.commit("cancel_sales_order", so=so["document"]["number"], reason="x")
    assert cancel["error"]["code"] == "PRECONDITION_FAILED"
    so2 = agent.ok("create_sales_order", customer="GLOBEX", lines=[{"sku": "BOLT-3", "qty": 10}])
    assert (
        agent.ok("cancel_sales_order", so=so2["document"]["number"], reason="duplicate")[
            "document"
        ]["status"]
        == "cancelled"
    )
