"""Append-only event log helpers (DESIGN.md §10)."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, select

from anerp.core.ids import iso
from anerp.events.models import Event


def emit(
    session: Session,
    type_: str,
    *,
    document_type: str | None,
    document_id: str | None,
    number: str | None,
    status: str | None,
    summary: str,
    actor_id: str | None,
    receipt_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Event:
    payload = {
        "document_type": document_type,
        "document_id": document_id,
        "number": number,
        "status": status,
        "receipt_id": receipt_id,
        "summary": summary,
    }
    if extra:
        payload.update(extra)
    event = Event(
        type=type_,
        document_type=document_type,
        document_id=document_id,
        receipt_id=receipt_id,
        actor_id=actor_id,
        payload_json=payload,
    )
    session.add(event)
    session.flush()
    return event


def event_to_dict(e: Event) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "type": e.type,
        "document_type": e.document_type,
        "document_id": e.document_id,
        "receipt_id": e.receipt_id,
        "actor_id": e.actor_id,
        "payload": e.payload_json,
        "occurred_at": iso(e.occurred_at),
    }


def poll(
    session: Session, after_seq: int = 0, types: list[str] | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    seq_col = col(Event.seq)
    stmt = (
        select(Event).where(seq_col > after_seq).order_by(seq_col).limit(min(max(limit, 1), 1000))
    )
    if types:
        stmt = stmt.where(col(Event.type).in_(types))
    return [event_to_dict(e) for e in session.exec(stmt).all()]


def latest_seq(session: Session) -> int:
    row = session.exec(select(Event.seq).order_by(col(Event.seq).desc()).limit(1)).first()
    return int(row) if row else 0
