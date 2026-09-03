"""Balances are always computed from lines (DESIGN.md §8.1: no cached balance column)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from anerp.finance.models import JournalEntry, JournalLine
from anerp.masterdata.models import Account


def account_balance(
    session: Session, account_code: str, as_of: date | None = None
) -> dict[str, Any]:
    stmt = (
        select(
            func.coalesce(func.sum(JournalLine.debit_cents), 0),
            func.coalesce(func.sum(JournalLine.credit_cents), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)  # type: ignore[arg-type]
        .where(JournalLine.account_code == account_code)
    )
    if as_of is not None:
        stmt = stmt.where(JournalEntry.posting_date <= as_of)
    debit, credit = session.exec(stmt).one()
    return {
        "account": account_code,
        "as_of": as_of.isoformat() if as_of else None,
        "debit_cents": int(debit),
        "credit_cents": int(credit),
        "net_cents": int(debit) - int(credit),
    }


def trial_balance(session: Session, period_code: str | None = None) -> dict[str, Any]:
    stmt = (
        select(
            JournalLine.account_code,
            func.coalesce(func.sum(JournalLine.debit_cents), 0),
            func.coalesce(func.sum(JournalLine.credit_cents), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)  # type: ignore[arg-type]
        .group_by(JournalLine.account_code)
    )
    if period_code:
        stmt = stmt.where(JournalEntry.period_code == period_code)
    totals = {code: (int(d), int(c)) for code, d, c in session.exec(stmt).all()}
    accounts = session.exec(select(Account).order_by(col(Account.code))).all()
    rows = []
    total_debit = total_credit = 0
    for acct in accounts:
        d, c = totals.get(acct.code, (0, 0))
        total_debit += d
        total_credit += c
        rows.append(
            {
                "code": acct.code,
                "name": acct.name,
                "type": acct.type,
                "debit_cents": d,
                "credit_cents": c,
                "net_cents": d - c,
            }
        )
    return {
        "period": period_code,
        "accounts": rows,
        "total_debit_cents": total_debit,
        "total_credit_cents": total_credit,
        "is_balanced": total_debit == total_credit,
    }
