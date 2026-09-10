"""The two discovery tools and the fiscal-period sort order (DESIGN.md §7.5).

A second client hit all three of these: it could not find the current period through
`search_documents`, could not learn the legal `type` values without provoking a
VALIDATION_ERROR, and got 36 periods back oldest-code-first.
"""

from __future__ import annotations

from datetime import date

from anerp.core.dispatch import run_query
from anerp.models import DOCUMENT_TYPES
from tests.conftest import AGENT, Client


def test_get_current_period_finds_today(kernel, agent: Client) -> None:
    current = agent.query("get_current_period")
    today = date.fromisoformat(current["as_of"])
    period = current["period"]
    assert date.fromisoformat(period["start_date"]) <= today
    assert today <= date.fromisoformat(period["end_date"])
    assert period["code"] == today.strftime("%Y-%m")
    # The seed leaves the month we are in open, and the checklist comes along for the ride so a
    # client does not need a second call to decide whether it can post.
    assert current["is_open"] and period["status"] == "open"
    assert current["close_readiness"]["period"] == period["code"]
    assert current["nearest_open_period"] is None
    # Same period, same payload as the code-addressed tool.
    assert agent.query("get_period", period_code=period["code"])["period"] == period


def test_get_current_period_names_a_fallback_once_today_is_closed(kernel, agent: Client) -> None:
    code = agent.query("get_current_period")["period"]["code"]
    assert agent.ok("close_period", period=code, reason="month end")["ok"]

    current = agent.query("get_current_period")
    assert current["period"]["code"] == code and not current["is_open"]
    fallback = current["nearest_open_period"]
    assert fallback is not None and fallback["status"] == "open" and fallback["code"] != code


def test_list_document_types_covers_every_type_search_accepts(kernel, agent: Client) -> None:
    listed = agent.query("list_document_types")
    assert listed["count"] == len(DOCUMENT_TYPES)
    names = [t["type"] for t in listed["types"]]
    assert names == sorted(DOCUMENT_TYPES)
    # Every advertised value is one search_documents actually takes.
    for name in names:
        assert agent.query("search_documents", type=name)["type"] == name

    by_name = {t["type"]: t for t in listed["types"]}
    po = by_name["PurchaseOrder"]
    assert po["number_prefix"] == "PO" and po["identifier_field"] == "number"
    assert po["party_field"] == "supplier_id"
    assert po["filters"] == ["status", "party", "date_from", "date_to", "number_prefix"]
    assert po["order_by"] == "created_at desc"
    # Master data carries no document number, so number_prefix is not a filter for it.
    item = by_name["Item"]
    assert item["number_prefix"] is None and item["identifier_field"] == "sku"
    assert "number_prefix" not in item["filters"] and item["party_field"] is None
    assert by_name["FiscalPeriod"]["order_by"] == "start_date desc"

    one = agent.query("list_document_types", type="SalesOrder")
    assert one["count"] == 1 and one["types"] == [by_name["SalesOrder"]]


def test_list_document_types_rejects_an_unknown_type(kernel) -> None:
    r = run_query("list_document_types", {"type": "Nope"}, AGENT)
    assert not r["ok"] and r["error"]["code"] == "VALIDATION_ERROR"
    assert "PurchaseOrder" in r["error"]["details"]["known"]


def test_fiscal_periods_come_back_newest_first(kernel, agent: Client) -> None:
    found = agent.query("search_documents", type="FiscalPeriod", limit=5)
    assert found["order_by"] == "start_date desc"
    codes = [row["number"] for row in found["items"]]
    assert codes == sorted(codes, reverse=True)
    # The whole calendar is seeded in one transaction, so created_at cannot separate the rows:
    # before the fix the first page started at the oldest period instead of the newest.
    every = agent.query("search_documents", type="FiscalPeriod", limit=500)["items"]
    assert len({row["created_at"] for row in every}) < len(every)
    assert codes[0] == max(row["number"] for row in every)
    current = agent.query("get_current_period")["period"]["code"]
    assert codes[0] >= current


def test_other_types_still_sort_on_created_at(kernel, agent: Client) -> None:
    agent.ok(
        "create_purchase_order",
        supplier="ACME",
        lines=[{"sku": "HOSE-10M", "qty": 1, "unit_cost": "25.00"}],
    )
    agent.ok(
        "create_purchase_order",
        supplier="BOLT",
        lines=[{"sku": "FLANGE-4", "qty": 2, "unit_cost": "15.00"}],
    )
    found = agent.query("search_documents", type="PurchaseOrder")
    assert found["order_by"] == "created_at desc"
    stamps = [row["created_at"] for row in found["items"]]
    assert stamps == sorted(stamps, reverse=True)
