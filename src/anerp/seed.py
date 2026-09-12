"""Seed data. Kernel data (chart of accounts, periods) is written directly; business data goes
through `core.dispatch` like any other client (DESIGN.md §3)."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from anerp.core.ids import utcnow
from anerp.finance.periods import ensure_periods
from anerp.masterdata.models import Account

log = logging.getLogger("anerp.seed")

CHART_OF_ACCOUNTS = [
    ("1000", "Cash", "asset"),
    ("1200", "Accounts receivable", "asset"),
    ("1300", "Inventory", "asset"),
    ("1400", "GR/IR clearing", "asset"),
    ("2000", "Accounts payable", "liability"),
    ("3000", "Owner's equity", "equity"),
    ("4000", "Sales revenue", "revenue"),
    ("5000", "Cost of goods sold", "expense"),
    ("5100", "Operating expense", "expense"),
    ("5200", "Purchase price variance", "expense"),
]

SEED_ACTOR = "system:seed"


SEED_YEARS = (2025, 2026, 2027)


def baseline_periods(today: date | None = None) -> dict[str, str]:
    """The baseline fixture's calendar, relative to `today`: the month before last is closed, last
    month (the first open period, where the opening balances are dated) and this month are open.
    Relative so that "close last month" is always a real task and "post into the closed month" is
    always refused, whatever the date."""
    today = today or utcnow().date()
    prev = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    closed_end = prev - timedelta(days=1)
    return {
        "closed_period": closed_end.strftime("%Y-%m"),
        "closed_period_end": closed_end.isoformat(),
        "open_period": prev.strftime("%Y-%m"),
        "opening_date": prev.isoformat(),
    }


_PERIODS = baseline_periods()
CLOSED_PERIOD = _PERIODS["closed_period"]
OPEN_PERIOD = _PERIODS["open_period"]  # last month: open, holds the opening balances
OPENING_DATE = _PERIODS["opening_date"]


def seed_kernel(session: Session, year: int | None = None) -> dict[str, int]:
    """Chart of accounts and fiscal periods (2025-2027 plus the current year). Idempotent."""
    year = year or utcnow().year
    accounts = 0
    for code, name, type_ in CHART_OF_ACCOUNTS:
        if session.exec(select(Account).where(Account.code == code)).first() is None:
            session.add(Account(code=code, name=name, type=type_))
            accounts += 1
    periods = sum(
        len(ensure_periods(session, y)) for y in sorted({*SEED_YEARS, year - 1, year, year + 1})
    )
    session.flush()
    return {"accounts": accounts, "periods": periods}


def _call(
    session: Session, tool: str, payload: dict[str, Any], actor_id: str, key: str
) -> dict[str, Any]:
    """Dispatch a commit inside the caller's transaction (session-bound dispatch), so a fixture
    is applied atomically: `anerp seed` commits once at the end and `reset_and_seed` ends its
    single transaction with the system.reset event and receipt."""
    from anerp.core.dispatch import dispatch
    from anerp.core.envelope import Actor, Envelope, local_principal

    session.flush()
    result = dispatch(
        Envelope(
            tool=tool,
            mode="commit",
            idempotency_key=f"seed:{key}",
            actor=Actor(id=actor_id, kind="admin"),
            payload=payload,
        ),
        principal=local_principal(actor_id),
        session=session,
    )
    if not result.get("ok"):
        raise RuntimeError(f"seed step {tool} failed: {result.get('error')}")
    return result


SUPPLIERS = (("ACME", "ACME Industrial", 30), ("BOLT", "Boltworks Ltd", 45))
CUSTOMERS = (
    ("NORTH", "Northgate Marine", "25000.00", 30),
    ("HARB", "Harborline Yachts", "5000.00", 14),
)
ITEMS = (  # sku, name, standard cost, list price, opening on-hand
    ("PUMP-SM", "Bilge pump, small", "400.00", "650.00", 0),
    ("VALVE-2IN", "Ball valve 2 inch", "50.00", "80.00", 5),
    ("HOSE-10M", "Reinforced hose 10 m", "25.00", "40.00", 40),
    ("FLANGE-4", "Flange 4 bolt", "15.00", "24.00", 100),
)


def seed_fixture(
    session: Session, name: str = "baseline", actor_id: str = SEED_ACTOR
) -> dict[str, Any]:
    """`empty`: chart of accounts and periods only. `baseline`: the demo master data, opening capital
    and opening stock as opening journal entries (through the dispatcher) dated the first of last
    month, and the month before last closed (`baseline_periods`).
    Runs inside the caller's transaction: all or nothing."""
    counts = seed_kernel(session)
    if name == "empty":
        session.flush()
        return counts
    if name != "baseline":
        raise ValueError(f"unknown fixture {name}")
    steps = 0
    for code, sname, terms in SUPPLIERS:
        _call(
            session,
            "create_supplier",
            {"code": code, "name": sname, "payment_terms_days": terms},
            actor_id,
            f"supplier:{code}",
        )
        steps += 1
    for code, cname, limit, terms in CUSTOMERS:
        _call(
            session,
            "create_customer",
            {"code": code, "name": cname, "credit_limit": limit, "payment_terms_days": terms},
            actor_id,
            f"customer:{code}",
        )
        steps += 1
    for sku, iname, cost, price, on_hand in ITEMS:
        # Opening stock is an opening balance: create_item posts Dr 1300 Inventory / Cr 3000 Equity
        # at standard cost and sets on_hand, so no purchase order or GR/IR balance is left behind.
        _call(
            session,
            "create_item",
            {
                "sku": sku,
                "name": iname,
                "standard_cost": cost,
                "list_price": price,
                "is_stocked": True,
                "opening_qty": on_hand,
                "opening_date": OPENING_DATE,
            },
            actor_id,
            f"item:{sku}",
        )
        steps += 1
    _call(
        session,
        "post_journal_entry",
        {
            "memo": "Opening capital",
            "posting_date": OPENING_DATE,
            "lines": [
                {"account": "1000", "debit": "250000.00"},
                {"account": "3000", "credit": "250000.00"},
            ],
        },
        actor_id,
        "opening-capital",
    )
    _call(session, "close_period", {"period": CLOSED_PERIOD}, actor_id, f"close:{CLOSED_PERIOD}")
    steps += 2
    counts["dispatched_steps"] = steps
    return counts
