"""Append-only event log (DESIGN.md §10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from anerp.core.ids import utcnow


class Event(SQLModel, table=True):
    __tablename__ = "event"
    seq: int | None = Field(default=None, primary_key=True)
    type: str = Field(max_length=64, index=True)
    document_type: str | None = Field(default=None, max_length=32)
    document_id: str | None = Field(default=None, max_length=26, index=True)
    receipt_id: str | None = Field(default=None, max_length=26)
    actor_id: str | None = Field(default=None, max_length=128)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    occurred_at: datetime = Field(default_factory=utcnow)
