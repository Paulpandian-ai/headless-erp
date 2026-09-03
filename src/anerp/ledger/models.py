"""Kernel tables: idempotency, receipts, keys, tokens, sequences (DESIGN.md §5.6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from anerp.core.ids import new_ulid, utcnow


class IdempotencyRecord(SQLModel, table=True):
    __tablename__ = "idempotency_record"
    key: str = Field(primary_key=True, max_length=128)
    tool_name: str = Field(max_length=64)
    request_hash: str = Field(max_length=80)
    response_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    receipt_id: str | None = Field(default=None, max_length=26)
    created_at: datetime = Field(default_factory=utcnow)


class Receipt(SQLModel, table=True):
    __tablename__ = "receipt"
    id: str = Field(default_factory=new_ulid, primary_key=True, max_length=26)
    tool_name: str = Field(max_length=64, index=True)
    actor_id: str = Field(max_length=128, index=True)
    actor_kind: str = Field(max_length=8)
    on_behalf_of: str | None = Field(default=None, max_length=128)
    document_type: str | None = Field(default=None, max_length=32)
    document_id: str | None = Field(default=None, max_length=26, index=True)
    document_number: str | None = Field(default=None, max_length=16)
    before_hash: str = Field(max_length=80)
    action_hash: str = Field(max_length=80)
    after_hash: str = Field(max_length=80)
    signature: str
    public_key_id: str = Field(max_length=26)
    signed_at: datetime = Field(default_factory=utcnow)
    idempotency_key: str | None = Field(default=None, max_length=128)
    payload_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    projection_json: dict = Field(default_factory=dict, sa_column=Column(JSON))


class ServerKey(SQLModel, table=True):
    __tablename__ = "server_key"
    id: str = Field(default_factory=new_ulid, primary_key=True, max_length=26)
    public_key_pem: str
    private_key_pem: str | None = None  # POC: rotated keys are persisted here; env key stays in env
    created_at: datetime = Field(default_factory=utcnow)
    retired_at: datetime | None = None


class ApiToken(SQLModel, table=True):
    __tablename__ = "api_token"
    id: str = Field(default_factory=new_ulid, primary_key=True, max_length=26)
    token_hash: str = Field(index=True, unique=True, max_length=80)
    subject: str = Field(max_length=128, index=True)
    kind: str = Field(max_length=8)  # agent | human | admin
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_by: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    last_used_at: datetime | None = None


class DocumentSequence(SQLModel, table=True):
    __tablename__ = "document_sequence"
    prefix: str = Field(primary_key=True, max_length=8)
    next_value: int = 1


class PolicyVersion(SQLModel, table=True):
    __tablename__ = "policy_version"
    id: str = Field(default_factory=new_ulid, primary_key=True, max_length=26)
    version: int = Field(index=True)
    yaml_text: str
    policy_hash: str = Field(max_length=80)
    comment: str = ""
    updated_by: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=utcnow)
    is_active: bool = True
