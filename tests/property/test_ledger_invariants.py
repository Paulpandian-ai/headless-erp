"""Hypothesis: the trial balance stays balanced under random journal generation; reversals mirror."""

from __future__ import annotations

from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlmodel import select

from anerp import db
from anerp.core.projection import JournalSpec, LineSpec
from anerp.finance.models import JournalLine
from anerp.ledger.posting import post_journal, reversal_spec, validate_journal
from anerp.ledger.trial_balance import trial_balance
from anerp.seed import CHART_OF_ACCOUNTS, seed_kernel

CODES = [c for c, _, _ in CHART_OF_ACCOUNTS]


def _fresh_session():
    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    db.init_db(engine)
    s = db.new_session()
    seed_kernel(s, 2026)
    s.commit()
    return s


amounts = st.lists(
    st.tuples(st.sampled_from(CODES), st.integers(min_value=1, max_value=10_000_000)),
    min_size=1,
    max_size=6,
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(entries=st.lists(st.tuples(amounts, st.sampled_from(CODES)), min_size=1, max_size=15))
def test_random_balanced_entries_keep_tb_balanced(entries) -> None:
    s = _fresh_session()
    try:
        for debits, credit_code in entries:
            total = sum(a for _, a in debits)
            lines = [LineSpec(code, debit_cents=a) for code, a in debits] + [
                LineSpec(credit_code, credit_cents=total)
            ]
            post_journal(s, JournalSpec(date(2026, 3, 15), "random", "Test", "x", lines))
            s.commit()
            tb = trial_balance(s, "2026-03")
            assert tb["is_balanced"]
            assert tb["total_debit_cents"] == tb["total_credit_cents"]
    finally:
        s.close()
        db.set_engine(None)


@settings(max_examples=40, deadline=None)
@given(debits=amounts, credit_code=st.sampled_from(CODES))
def test_reversal_mirrors_and_never_mutates_original(debits, credit_code) -> None:
    s = _fresh_session()
    try:
        total = sum(a for _, a in debits)
        lines = [LineSpec(code, debit_cents=a) for code, a in debits] + [
            LineSpec(credit_code, credit_cents=total)
        ]
        original = post_journal(s, JournalSpec(date(2026, 4, 1), "orig", "Test", "x", lines))
        s.commit()
        before = [
            (line.account_code, line.debit_cents, line.credit_cents)
            for line in s.exec(
                select(JournalLine)
                .where(JournalLine.entry_id == original.id)
                .order_by(JournalLine.line_no)
            ).all()
        ]
        rev = post_journal(s, reversal_spec(s, original, date(2026, 4, 2), "rev", "Test", "x"))
        s.commit()
        after = [
            (line.account_code, line.debit_cents, line.credit_cents)
            for line in s.exec(
                select(JournalLine)
                .where(JournalLine.entry_id == original.id)
                .order_by(JournalLine.line_no)
            ).all()
        ]
        mirrored = [
            (line.account_code, line.debit_cents, line.credit_cents)
            for line in s.exec(
                select(JournalLine)
                .where(JournalLine.entry_id == rev.id)
                .order_by(JournalLine.line_no)
            ).all()
        ]
        assert before == after
        assert mirrored == [(c, cr, d) for c, d, cr in before]
        assert rev.reversal_of_id == original.id
        for code in {c for c, _, _ in before}:
            tb = trial_balance(s, "2026-04")
            row = next(r for r in tb["accounts"] if r["code"] == code)
            assert row["net_cents"] == 0
    finally:
        s.close()
        db.set_engine(None)


@given(
    debit=st.integers(min_value=0, max_value=1000), credit=st.integers(min_value=0, max_value=1000)
)
@settings(max_examples=30, deadline=None)
def test_validate_journal_rejects_unbalanced_and_single_sided(debit, credit) -> None:
    s = _fresh_session()
    try:
        spec = JournalSpec(
            date(2026, 1, 1),
            "m",
            "Test",
            "x",
            [LineSpec("1000", debit_cents=debit), LineSpec("2000", credit_cents=credit)],
        )
        problems = validate_journal(s, spec)
        if debit == credit and debit > 0:
            assert problems == []
        else:
            assert problems
    finally:
        s.close()
        db.set_engine(None)
