"""Per-type document numbering (PO-000123). Allocation happens inside the commit transaction."""

from __future__ import annotations

from sqlmodel import Session

from anerp.ledger.models import DocumentSequence
from anerp.models import NUMBER_PREFIXES

WIDTH = 6


def format_number(prefix: str, value: int) -> str:
    return f"{prefix}-{value:0{WIDTH}d}"


def peek_number(session: Session, document_type: str) -> str:
    prefix = NUMBER_PREFIXES[document_type]
    row = session.get(DocumentSequence, prefix)
    value = row.next_value if row else 1
    return format_number(prefix, value) + " (projected)"


def allocate_number(session: Session, document_type: str) -> str:
    prefix = NUMBER_PREFIXES[document_type]
    row = session.get(DocumentSequence, prefix, with_for_update=not _is_sqlite(session))
    if row is None:
        row = DocumentSequence(prefix=prefix, next_value=1)
        session.add(row)
    value = row.next_value
    row.next_value = value + 1
    session.add(row)
    session.flush()
    return format_number(prefix, value)


def _is_sqlite(session: Session) -> bool:
    bind = session.get_bind()
    return bind.dialect.name == "sqlite"
