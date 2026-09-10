"""Period close and reopen, closed-period trap."""

from __future__ import annotations

from datetime import date

from tests.conftest import Client


def test_close_and_reopen(kernel, agent: Client) -> None:
    period = date.today().strftime("%Y-%m")
    sim = agent.simulate("close_period", period=period)
    assert sim["ok"] and sim["policy"]["decision"] == "allow"
    assert sim["projected_effects"]["details"]["checklist"]["ready"]
    closed = agent.ok("close_period", period=period)
    assert closed["document"]["status"] == "closed"
    je = agent.commit(
        "post_journal_entry",
        memo="late",
        lines=[{"account": "5100", "debit": "10.00"}, {"account": "1000", "credit": "10.00"}],
    )
    assert je["error"]["code"] == "PERIOD_CLOSED"
    sim_je = agent.simulate(
        "post_journal_entry",
        memo="late",
        lines=[{"account": "5100", "debit": "10.00"}, {"account": "1000", "credit": "10.00"}],
    )
    assert sim_je["commit_would_fail_with"] == "PERIOD_CLOSED"
    so = agent.ok("create_sales_order", customer="NORTH", lines=[{"sku": "FLANGE-4", "qty": 1}])
    assert (
        agent.commit("ship_order", so=so["document"]["number"])["error"]["code"] == "PERIOD_CLOSED"
    )
    assert (
        agent.commit("reopen_period", period=period, reason="")["error"]["code"]
        == "VALIDATION_ERROR"
    )
    reopened = agent.ok("reopen_period", period=period, reason="late invoices")
    assert reopened["document"]["status"] == "open"
    assert agent.ok(
        "post_journal_entry",
        memo="late",
        lines=[{"account": "5100", "debit": "10.00"}, {"account": "1000", "credit": "10.00"}],
    )["document"]["number"].startswith("JE-")


def test_manual_journal_and_reversal(kernel, agent: Client) -> None:
    bad = agent.commit(
        "post_journal_entry",
        memo="unbalanced",
        lines=[{"account": "5100", "debit": "10.00"}, {"account": "1000", "credit": "9.00"}],
    )
    assert bad["error"]["code"] == "VALIDATION_ERROR"
    big = agent.simulate(
        "post_journal_entry",
        memo="big",
        lines=[{"account": "5100", "debit": "60000.00"}, {"account": "1000", "credit": "60000.00"}],
    )
    assert any("large_manual_je" in w for w in big["validation"]["warnings"])
    je = agent.ok(
        "post_journal_entry",
        memo="accrual",
        lines=[
            {"account": "5100", "debit": "100.00", "description": "rent"},
            {"account": "2000", "credit": "100.00"},
        ],
    )
    number = je["document"]["number"]
    rev = agent.ok("reverse_journal_entry", je=number, reason="reverse accrual")
    assert rev["document"]["number"] != number
    original = agent.query("get_document", id_or_number=number)
    assert original["status"] == "reversed" and original["reversed_by"] == [
        rev["document"]["number"]
    ]
    assert (
        agent.commit("reverse_journal_entry", je=number, reason="again")["error"]["code"]
        == "PRECONDITION_FAILED"
    )
    explain = agent.query("explain_balance", account_code="5100")
    assert explain["reversal_pairs"] == [
        {"original": number, "reversal": rev["document"]["number"]}
    ]
    assert explain["balance"]["net_cents"] == 0
