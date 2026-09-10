"""Seed data. Kernel data (chart of accounts, periods) is written directly; business data goes
through `core.dispatch` like any other client (DESIGN.md §3)."""

from __future__ import annotations

import logging
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
CLOSED_PERIOD = "2026-08"  # the baseline fixture keeps 2026-08 closed and 2026-09 open


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
    """Dispatch a commit in-process. The seed shares the caller's engine, not its session."""
    from anerp.core.dispatch import dispatch
    from anerp.core.envelope import Actor, Envelope, local_principal

    # Flush the caller's transaction so dispatch (own session) can see kernel rows on SQLite.
    session.commit()
    result = dispatch(
        Envelope(
            tool=tool,
            mode="commit",
            idempotency_key=f"seed:{key}",
            actor=Actor(id=actor_id, kind="admin"),
            payload=payload,
        ),
        principal=local_principal(actor_id),
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
    """`empty`: chart of accounts and periods only. `baseline`: the demo master data, opening capital,
    opening stock received through the dispatcher, and period 2026-08 closed."""
    counts = seed_kernel(session)
    if name == "empty":
        session.commit()
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
    for sku, iname, cost, price, _on_hand in ITEMS:
        _call(
            session,
            "create_item",
            {
                "sku": sku,
                "name": iname,
                "standard_cost": cost,
                "list_price": price,
                "is_stocked": True,
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
            "lines": [
                {"account": "1000", "debit": "250000.00"},
                {"account": "3000", "credit": "250000.00"},
            ],
        },
        actor_id,
        "opening-capital",
    )
    steps += 1
    stock_lines = [
        {"sku": sku, "qty": on_hand, "unit_cost": cost}
        for sku, _n, cost, _p, on_hand in ITEMS
        if on_hand > 0
    ]
    po = _call(
        session,
        "create_purchase_order",
        {"supplier": "ACME", "lines": stock_lines, "memo": "Opening stock"},
        actor_id,
        "opening-po",
    )
    po_number = po["document"]["number"]
    _call(
        session, "receive_goods", {"po": po_number}, actor_id, "opening-grn"
    )  # admin actor: posts directly
    inv = _call(
        session,
        "post_supplier_invoice",
        {"po": po_number, "supplier_reference": "ACME-0001", "lines": stock_lines},
        actor_id,
        "opening-sinv",
    )
    _call(session, "pay_supplier", {"invoice": inv["document"]["number"]}, actor_id, "opening-pay")
    _call(session, "close_period", {"period": CLOSED_PERIOD}, actor_id, f"close:{CLOSED_PERIOD}")
    steps += 5
    counts["dispatched_steps"] = steps
    return counts
