"""End-to-end order-to-cash with credit-limit and stock traps."""

from __future__ import annotations

from tests.conftest import Client, tb_balanced


def test_o2c_simple(kernel, agent: Client) -> None:
    so = agent.ok("create_sales_order", customer="NORTH", lines=[{"sku": "VALVE-2IN", "qty": 5}])
    assert so["document"]["status"] == "open" and so["effects"]["details"]["total"] == "400.00"
    so_number = so["document"]["number"]
    inv_before = agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"]
    shp = agent.ok("ship_order", so=so_number)
    assert shp["effects"]["details"]["cogs"] == "250.00"
    assert (
        agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"] == inv_before - 5
    )
    assert agent.query("get_document", id_or_number=so_number)["status"] == "shipped"
    cinv = agent.ok("issue_customer_invoice", so=so_number)
    assert cinv["effects"]["details"]["total"] == "400.00"
    assert (
        agent.query("list_open_items", kind="ar", party="NORTH")["total_remaining_cents"] == 40000
    )
    assert agent.query("get_account_balance", account_code="4000")["net_cents"] == -40000
    rcpt = agent.ok("record_customer_payment", invoice=cinv["document"]["number"], amount="150.00")
    assert rcpt["effects"]["details"]["remaining_after"] == "250.00"
    assert (
        agent.ok("record_customer_payment", invoice=cinv["document"]["number"])["effects"][
            "details"
        ]["remaining_after"]
        == "0.00"
    )
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
    sim = agent.simulate(
        "create_sales_order", customer="HARB", lines=[{"sku": "PUMP-SM", "qty": 10}]
    )  # 6,500 > 5,000
    assert (
        sim["ok"]
        and sim["policy"]["decision"] == "deny"
        and sim["commit_would_fail_with"] == "CREDIT_LIMIT_EXCEEDED"
    )
    assert sim["projected_effects"]["details"]["credit_check"]["exposure_after_cents"] == 650000
    res = agent.commit("create_sales_order", customer="HARB", lines=[{"sku": "PUMP-SM", "qty": 10}])
    assert not res["ok"] and res["error"]["code"] == "CREDIT_LIMIT_EXCEEDED"
    assert agent.query("search_documents", type="SalesOrder", party="HARB")["count"] == 0
    assert (
        agent.ok("create_sales_order", customer="HARB", lines=[{"sku": "PUMP-SM", "qty": 7}])[
            "document"
        ]["status"]
        == "open"
    )


def test_out_of_stock_trap(kernel, agent: Client) -> None:
    so = agent.ok("create_sales_order", customer="NORTH", lines=[{"sku": "PUMP-SM", "qty": 3}])
    sim = agent.simulate("ship_order", so=so["document"]["number"])
    assert (
        sim["policy"]["decision"] == "deny"
        and sim["commit_would_fail_with"] == "INSUFFICIENT_STOCK"
    )
    assert (
        agent.commit("ship_order", so=so["document"]["number"])["error"]["code"]
        == "INSUFFICIENT_STOCK"
    )
    so2 = agent.ok("create_sales_order", customer="NORTH", lines=[{"sku": "HOSE-10M", "qty": 45}])
    assert (
        agent.commit("ship_order", so=so2["document"]["number"])["error"]["code"]
        == "INSUFFICIENT_STOCK"
    )
    partial = agent.ok(
        "ship_order", so=so2["document"]["number"], lines=[{"sku": "HOSE-10M", "qty": 40}]
    )
    assert partial["document"]["status"] == "posted"
    assert (
        agent.query("get_document", id_or_number=so2["document"]["number"])["status"]
        == "partially_shipped"
    )
    assert agent.query("get_inventory", sku="HOSE-10M")["items"][0]["on_hand_qty"] == 0


def test_o2c_reversals_and_credit_note(kernel, agent: Client) -> None:
    so = agent.ok("create_sales_order", customer="NORTH", lines=[{"sku": "VALVE-2IN", "qty": 4}])
    shp = agent.ok("ship_order", so=so["document"]["number"])
    before = agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"]
    rev = agent.ok("reverse_shipment", shipment=shp["document"]["number"], reason="returned")
    assert rev["journal_entry"]
    assert agent.query("get_inventory", sku="VALVE-2IN")["items"][0]["on_hand_qty"] == before + 4
    assert agent.query("get_document", id_or_number=so["document"]["number"])["status"] == "open"
    shp2 = agent.ok("ship_order", so=so["document"]["number"])
    cinv = agent.ok("issue_customer_invoice", so=so["document"]["number"])
    assert (
        agent.commit("reverse_shipment", shipment=shp2["document"]["number"], reason="too late")[
            "error"
        ]["code"]
        == "PRECONDITION_FAILED"
    )
    cn = agent.ok(
        "issue_credit_note",
        invoice=cinv["document"]["number"],
        amount="80.00",
        reason="one damaged",
    )
    assert cn["journal_entry"]
    assert (
        agent.query("list_open_items", kind="ar", party="NORTH")["total_remaining_cents"] == 24000
    )
    pay = agent.ok("record_customer_payment", invoice=cinv["document"]["number"])
    assert agent.ok(
        "reverse_customer_payment", payment=pay["document"]["number"], reason="bounced"
    )["ok"]
    assert (
        agent.query("list_open_items", kind="ar", party="NORTH")["total_remaining_cents"] == 24000
    )
    assert tb_balanced(agent)
    assert (
        agent.commit("cancel_sales_order", so=so["document"]["number"], reason="x")["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    so2 = agent.ok("create_sales_order", customer="NORTH", lines=[{"sku": "FLANGE-4", "qty": 10}])
    assert (
        agent.ok("cancel_sales_order", so=so2["document"]["number"], reason="duplicate")[
            "document"
        ]["status"]
        == "cancelled"
    )
