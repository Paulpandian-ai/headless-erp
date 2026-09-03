from __future__ import annotations

from tests.conftest import Client


def test_master_data_lifecycle(kernel, agent: Client) -> None:
    sim = agent.simulate("create_supplier", code="ACME", name="dup")
    assert not sim["ok"] and sim["error"]["code"] == "PRECONDITION_FAILED"
    s = agent.ok("create_supplier", code="NEW", name="New Co", payment_terms_days=10)
    assert s["document"]["number"] == "NEW"
    agent.ok("create_customer", code="CUST", name="C", credit_limit="100.00")
    agent.ok("create_item", sku="THING", name="T", standard_cost="1.50", list_price="3.00")
    agent.ok("create_account", code="5300", name="Travel", type="expense")
    assert (
        agent.commit("create_account", code="5300", name="Travel", type="expense")["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    off = agent.ok("deactivate_item", ref="THING", reason="obsolete")
    assert (
        off["document"]["status"] is None
        and off["effects"]["documents"][0]["fields"]["is_active"] is False
    )
    assert (
        agent.commit(
            "create_purchase_order",
            supplier="NEW",
            lines=[{"sku": "THING", "qty": 1, "unit_cost": "1.00"}],
        )["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    assert (
        agent.commit("deactivate_item", ref="THING", reason="again")["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    agent.ok("activate_item", ref="THING")
    assert agent.ok(
        "create_purchase_order",
        supplier="NEW",
        lines=[{"sku": "THING", "qty": 1, "unit_cost": "1.00"}],
    )["ok"]
    agent.ok("deactivate_account", ref="5300", reason="unused")
    assert (
        agent.commit(
            "post_journal_entry",
            memo="x",
            lines=[{"account": "5300", "debit": "1.00"}, {"account": "1000", "credit": "1.00"}],
        )["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    caps = agent.query("list_capabilities")
    assert caps["count"] >= 50 and "procurement" in caps["modules"]
    desc = agent.query("describe_tool", name="receive_goods")
    assert (
        desc["compensating_tool"] == "reverse_goods_receipt"
        and "Simulate first" in desc["description"]
    )
