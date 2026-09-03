"""Approval inbox (DESIGN.md §7.9)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field

from anerp.db import KernelRow


class ApprovalRequest(KernelRow, table=True):
    __tablename__ = "approval_request"
    document_type: str = Field(max_length=32, index=True)
    # None when the request was raised for a document that was never persisted (the tool could
    # not hold a pending version); the projection lives in projected_effects_json instead.
    document_id: str | None = Field(default=None, max_length=26, index=True)
    document_number: str | None = Field(default=None, max_length=16)
    tool_name: str = Field(max_length=64)
    request_hash: str | None = Field(default=None, max_length=80, index=True)
    requested_by: str = Field(max_length=128)
    reason: str = ""
    projected_effects_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="pending", max_length=16, index=True)
    decided_by: str | None = Field(default=None, max_length=128)
    decided_at: datetime | None = None
    decision_comment: str | None = None
    expires_at: datetime | None = None
