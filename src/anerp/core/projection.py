"""Projected effects: the pure output of a tool's `project()` (DESIGN.md §6.2 step 3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from anerp.core.ids import new_ulid

Action = str  # "create" | "update"


@dataclass
class DocumentEffect:
    type: str
    action: Action
    instance: Any
    changes: dict[str, Any] = field(default_factory=dict)
    primary: bool = False

    @property
    def projected_fields(self) -> dict[str, Any]:
        if self.action == "create":
            data = self.instance.model_dump(mode="json")
            data.pop("created_at", None)
            data.pop("updated_at", None)
            return data
        return dict(self.changes)


@dataclass
class LineSpec:
    account_code: str
    debit_cents: int = 0
    credit_cents: int = 0
    description: str = ""


@dataclass
class JournalSpec:
    posting_date: date
    memo: str
    source_type: str
    source_id: str
    lines: list[LineSpec]
    reversal_of_id: str | None = None
    id: str = field(default_factory=new_ulid)

    @property
    def total_debit(self) -> int:
        return sum(line.debit_cents for line in self.lines)

    @property
    def total_credit(self) -> int:
        return sum(line.credit_cents for line in self.lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "posting_date": self.posting_date.isoformat(),
            "memo": self.memo,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "reversal_of_id": self.reversal_of_id,
            "lines": [
                {
                    "account": line.account_code,
                    "debit_cents": line.debit_cents,
                    "credit_cents": line.credit_cents,
                    "description": line.description,
                }
                for line in self.lines
            ],
            "total_debit_cents": self.total_debit,
            "total_credit_cents": self.total_credit,
            "is_balanced": self.total_debit == self.total_credit,
        }


@dataclass
class InventoryDelta:
    item: Any
    sku: str
    qty_delta: int


@dataclass
class EventSpec:
    type: str
    summary: str
    document_type: str | None = None
    document: Any | None = None  # resolved to id/number at commit
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Compensation:
    tool: str
    payload_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class Projection:
    documents: list[DocumentEffect] = field(default_factory=list)
    journal: JournalSpec | None = None
    open_items: list[DocumentEffect] = field(default_factory=list)
    inventory: list[InventoryDelta] = field(default_factory=list)
    events: list[EventSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    touched: list[Any] = field(default_factory=list)
    compensation: Compensation | None = None
    # Called by the dispatcher when policy says requires_approval and the tool can
    # persist a pending version of the document instead of refusing (create_purchase_order).
    on_requires_approval: Callable[[], None] | None = None
    approval_reason: str | None = None
    # The persisted document a parked ApprovalRequest should point at when the primary effect is a
    # creation (e.g. receive_goods parks against the PurchaseOrder). Defaults to the primary
    # document when that one already exists.
    approval_target: Any | None = None
    approval_target_type: str | None = None
    # Returned once in the commit response, never stored in receipts or idempotency records.
    secret: dict[str, Any] | None = None
    # Admin-only escape hatches, still inside the single dispatcher transaction / receipt:
    # apply_hook runs inside the commit transaction (reset_and_seed); after_commit runs once
    # the transaction is durable (e.g. hot-swap the in-memory policy engine).
    apply_hook: Callable[[Any], dict[str, Any]] | None = None
    after_commit: Callable[[], None] | None = None

    @property
    def primary(self) -> DocumentEffect | None:
        """The explicitly marked primary document; else the first document unless a journal
        entry is the real subject (e.g. reverse_journal_entry), in which case None and the
        dispatcher reports the posted journal entry."""
        for d in self.documents:
            if d.primary:
                return d
        if self.journal is not None:
            return None
        return self.documents[0] if self.documents else None

    def balance_deltas(self) -> list[dict[str, Any]]:
        if self.journal is None:
            return []
        deltas: dict[str, int] = {}
        for line in self.journal.lines:
            deltas[line.account_code] = (
                deltas.get(line.account_code, 0) + line.debit_cents - line.credit_cents
            )
        return [{"account": code, "delta_cents": delta} for code, delta in sorted(deltas.items())]

    def create(self, type_: str, instance: Any, *, primary: bool = False) -> DocumentEffect:
        eff = DocumentEffect(type=type_, action="create", instance=instance, primary=primary)
        self.documents.append(eff)
        return eff

    def update(
        self, type_: str, instance: Any, changes: dict[str, Any], *, primary: bool = False
    ) -> DocumentEffect:
        eff = DocumentEffect(
            type=type_, action="update", instance=instance, changes=changes, primary=primary
        )
        self.documents.append(eff)
        return eff
