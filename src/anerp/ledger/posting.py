"""Double-entry posting: the only code that writes JournalEntry/JournalLine rows (DESIGN.md §8.1)."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from anerp.core.errors import AnerpError, ErrorCode, validation
from anerp.core.projection import JournalSpec, LineSpec
from anerp.finance.models import FiscalPeriod, JournalEntry, JournalLine
from anerp.ledger.sequences import allocate_number
from anerp.masterdata.models import Account


def find_period(session: Session, posting_date: date) -> FiscalPeriod | None:
    stmt = select(FiscalPeriod).where(
        FiscalPeriod.start_date <= posting_date, FiscalPeriod.end_date >= posting_date
    )
    return session.exec(stmt).first()


def validate_journal(session: Session, spec: JournalSpec) -> list[str]:
    """Return a list of human-readable problems; empty means the entry can be posted."""
    problems: list[str] = []
    if len(spec.lines) < 2:
        problems.append("a journal entry needs at least two lines")
    if spec.total_debit != spec.total_credit:
        problems.append(f"debits ({spec.total_debit}) do not equal credits ({spec.total_credit})")
    for i, line in enumerate(spec.lines, start=1):
        if (line.debit_cents > 0) == (line.credit_cents > 0):
            problems.append(f"line {i}: exactly one of debit/credit must be non-zero")
        if line.debit_cents < 0 or line.credit_cents < 0:
            problems.append(f"line {i}: amounts must be non-negative")
        acct = session.exec(select(Account).where(Account.code == line.account_code)).first()
        if acct is None:
            problems.append(f"line {i}: account {line.account_code} does not exist")
        elif not acct.is_active:
            problems.append(f"line {i}: account {line.account_code} is inactive")
    return problems


def post_journal(session: Session, spec: JournalSpec) -> JournalEntry:
    """Persist a balanced entry. Raises PERIOD_CLOSED / VALIDATION_ERROR; never partially writes."""
    problems = validate_journal(session, spec)
    if problems:
        raise validation("journal entry invalid: " + "; ".join(problems), problems=problems)
    period = find_period(session, spec.posting_date)
    if period is None:
        raise AnerpError(
            ErrorCode.NOT_FOUND, f"no fiscal period covers {spec.posting_date.isoformat()}"
        )
    if period.status != "open":
        raise AnerpError(
            ErrorCode.PERIOD_CLOSED,
            f"period {period.code} is closed",
            {"period": period.code, "posting_date": spec.posting_date.isoformat()},
        )
    entry = JournalEntry(
        id=spec.id,
        number=allocate_number(session, "JournalEntry"),
        period_id=period.id,
        period_code=period.code,
        posting_date=spec.posting_date,
        memo=spec.memo,
        source_type=spec.source_type,
        source_id=spec.source_id,
        reversal_of_id=spec.reversal_of_id,
        total_debit_cents=spec.total_debit,
    )
    session.add(entry)
    accounts = {
        a.code: a
        for a in session.exec(
            select(Account).where(Account.code.in_([line.account_code for line in spec.lines]))  # type: ignore[attr-defined]
        ).all()
    }
    for i, line in enumerate(spec.lines, start=1):
        session.add(
            JournalLine(
                entry_id=entry.id,
                line_no=i,
                account_id=accounts[line.account_code].id,
                account_code=line.account_code,
                debit_cents=line.debit_cents,
                credit_cents=line.credit_cents,
                description=line.description,
            )
        )
    session.flush()
    return entry


def reversal_spec(
    session: Session,
    original: JournalEntry,
    posting_date: date,
    memo: str,
    source_type: str,
    source_id: str,
) -> JournalSpec:
    """Mirror the original lines (swap Dr/Cr). The original is never mutated."""
    lines = session.exec(
        select(JournalLine).where(JournalLine.entry_id == original.id).order_by(JournalLine.line_no)  # type: ignore[arg-type]
    ).all()
    return JournalSpec(
        posting_date=posting_date,
        memo=memo,
        source_type=source_type,
        source_id=source_id,
        reversal_of_id=original.id,
        lines=[
            LineSpec(
                account_code=line.account_code,
                debit_cents=line.credit_cents,
                credit_cents=line.debit_cents,
                description=f"reversal: {line.description}",
            )
            for line in lines
        ],
    )
