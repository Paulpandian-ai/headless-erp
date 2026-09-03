"""Idempotency store (DESIGN.md §8.2). Records are written in the commit transaction."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from anerp.core.hashing import hash_obj
from anerp.ledger.models import IdempotencyRecord


def request_hash(tool_name: str, payload: dict[str, Any]) -> str:
    return hash_obj({"tool_name": tool_name, "payload": payload})


def lookup(session: Session, key: str) -> IdempotencyRecord | None:
    return session.get(IdempotencyRecord, key)


def store(
    session: Session,
    key: str,
    tool_name: str,
    req_hash: str,
    response: dict[str, Any],
    receipt_id: str | None,
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        key=key,
        tool_name=tool_name,
        request_hash=req_hash,
        response_json=response,
        receipt_id=receipt_id,
    )
    session.add(record)
    return record
