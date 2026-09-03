"""Finance tables: periods, journal entries, open items (DESIGN.md §5.3)."""

from __future__ import annotations

from datetime import date

from sqlmodel import Field

from anerp.db import KernelRow


class FiscalPeriod(KernelRow, table=True):
    __tablename__ = "fiscal_period"
    code: str = Field(index=True, unique=True, max_length=7)  # YYYY-MM
    start_date: date
    end_date: date
    status: str = Field(default="open", max_length=8)  # open | closed


class JournalEntry(KernelRow, table=True):
    __tablename__ = "journal_entry"
    number: str = Field(index=True, unique=True, max_length=16)
    period_id: str = Field(foreign_key="fiscal_period.id", index=True)
    period_code: str = Field(index=True, max_length=7)
    posting_date: date
    memo: str = ""
    source_type: str = Field(max_length=32)
    source_id: str = Field(max_length=26, index=True)
    reversal_of_id: str | None = Field(default=None, foreign_key="journal_entry.id")
    status: str = Field(default="posted", max_length=8)  # posted | reversed
    total_debit_cents: int = 0
    receipt_id: str | None = Field(default=None, max_length=26)


class JournalLine(KernelRow, table=True):
    __tablename__ = "journal_line"
    entry_id: str = Field(foreign_key="journal_entry.id", index=True)
    line_no: int = 1
    account_id: str = Field(foreign_key="account.id", index=True)
    account_code: str = Field(index=True, max_length=16)
    debit_cents: int = 0
    credit_cents: int = 0
    description: str = ""


class OpenItem(KernelRow, table=True):
    __tablename__ = "open_item"
    kind: str = Field(max_length=2, index=True)  # ap | ar
    party_id: str = Field(index=True, max_length=26)
    source_doc_type: str = Field(max_length=32)
    source_doc_id: str = Field(index=True, max_length=26)
    source_doc_number: str = Field(max_length=16)
    amount_cents: int
    remaining_cents: int
    due_date: date
    status: str = Field(default="open", max_length=16)  # open | partially_paid | paid | reversed
