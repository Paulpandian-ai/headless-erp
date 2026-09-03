"""Read-only query tools (DESIGN.md §7.5). Registered for every module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from anerp.core.context import ToolContext
from anerp.core.errors import not_found, validation
from anerp.core.registry import QueryTool, registry, tool
from anerp.documents import find_document, serialize, summary
from anerp.events.log import poll
from anerp.finance.models import FiscalPeriod, JournalEntry, JournalLine, OpenItem
from anerp.finance.periods import close_readiness
from anerp.ledger.receipts import verify_receipt
from anerp.ledger.trial_balance import account_balance, trial_balance
from anerp.masterdata.models import Customer, Item, Supplier
from anerp.models import DOCUMENT_TYPES


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetDocumentPayload(_Strict):
    type: str | None = Field(
        default=None,
        description="Document type, e.g. PurchaseOrder; optional when the number prefix identifies it",
    )
    id_or_number: str = Field(description="ULID or human number like PO-000123")


@tool
class GetDocument(QueryTool):
    name = "get_document"
    module = "query"
    scope = "documents:read"
    purpose = "Fetch one document with its lines, status, linked documents, journal entry, receipts and events."
    payload_model = GetDocumentPayload

    def run(self, ctx: ToolContext, payload: GetDocumentPayload) -> dict[str, Any]:
        found = find_document(ctx.session, payload.id_or_number, payload.type)
        if found is None:
            raise not_found(payload.type or "Document", payload.id_or_number)
        type_name, row = found
        return serialize(ctx.session, type_name, row)


class SearchPayload(_Strict):
    type: str = Field(description="Document type, e.g. PurchaseOrder, SupplierInvoice, SalesOrder")
    status: str | None = None
    party: str | None = Field(default=None, description="Supplier/customer code or id")
    number_prefix: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


@tool
class SearchDocuments(QueryTool):
    name = "search_documents"
    module = "query"
    scope = "documents:read"
    purpose = "List documents of one type filtered by status, party, creation date range or number prefix (paged, newest first)."
    payload_model = SearchPayload

    def run(self, ctx: ToolContext, payload: SearchPayload) -> dict[str, Any]:
        model = DOCUMENT_TYPES.get(payload.type)
        if model is None:
            raise validation(f"unknown document type {payload.type}", known=sorted(DOCUMENT_TYPES))
        stmt = select(model)
        if payload.status and hasattr(model, "status"):
            stmt = stmt.where(model.status == payload.status)  # type: ignore[attr-defined]
        if payload.party:
            party_id = _party_id(ctx, payload.party)
            for attr in ("supplier_id", "customer_id", "party_id"):
                if hasattr(model, attr):
                    stmt = stmt.where(getattr(model, attr) == party_id)
                    break
        if payload.number_prefix and hasattr(model, "number"):
            stmt = stmt.where(model.number.startswith(payload.number_prefix))  # type: ignore[attr-defined]
        if payload.date_from:
            stmt = stmt.where(
                model.created_at >= datetime.combine(payload.date_from, datetime.min.time())
            )  # type: ignore[attr-defined]
        if payload.date_to:
            stmt = stmt.where(
                model.created_at <= datetime.combine(payload.date_to, datetime.max.time())
            )  # type: ignore[attr-defined]
        stmt = stmt.order_by(model.created_at.desc()).offset(payload.offset).limit(payload.limit)  # type: ignore[attr-defined]
        rows = ctx.session.exec(stmt).all()
        return {
            "type": payload.type,
            "count": len(rows),
            "offset": payload.offset,
            "items": [summary(payload.type, r) for r in rows],
        }


def _party_id(ctx: ToolContext, ref: str) -> str:
    for model in (Supplier, Customer):
        row = (
            ctx.session.get(model, ref)
            or ctx.session.exec(select(model).where(model.code == ref)).first()
        )
        if row is not None:
            return row.id
    raise not_found("Party", ref)


class OpenItemsPayload(_Strict):
    kind: Literal["ap", "ar"]
    party: str | None = None
    overdue_only: bool = False
    as_of: date | None = None


@tool
class ListOpenItems(QueryTool):
    name = "list_open_items"
    module = "query"
    scope = "finance:read"
    purpose = "List AP or AR open items (unpaid invoices) with remaining amounts and due dates."
    payload_model = OpenItemsPayload

    def run(self, ctx: ToolContext, payload: OpenItemsPayload) -> dict[str, Any]:
        stmt = select(OpenItem).where(
            OpenItem.kind == payload.kind, OpenItem.status.in_(["open", "partially_paid"])
        )  # type: ignore[attr-defined]
        if payload.party:
            stmt = stmt.where(OpenItem.party_id == _party_id(ctx, payload.party))
        as_of = payload.as_of or ctx.now.date()
        if payload.overdue_only:
            stmt = stmt.where(OpenItem.due_date < as_of)
        rows = ctx.session.exec(stmt.order_by(OpenItem.due_date)).all()  # type: ignore[arg-type]
        items = []
        for r in rows:
            d = r.model_dump(mode="json")
            d["overdue"] = r.due_date < as_of
            d["days_to_due"] = (r.due_date - as_of).days
            items.append(d)
        return {
            "kind": payload.kind,
            "as_of": as_of.isoformat(),
            "count": len(items),
            "total_remaining_cents": sum(r.remaining_cents for r in rows),
            "items": items,
        }


class BalancePayload(_Strict):
    account_code: str
    as_of_date: date | None = None


@tool
class GetAccountBalance(QueryTool):
    name = "get_account_balance"
    module = "query"
    scope = "finance:read"
    purpose = "Debit/credit totals and net balance for one GL account, optionally as of a date."
    payload_model = BalancePayload

    def run(self, ctx: ToolContext, payload: BalancePayload) -> dict[str, Any]:
        ctx.get_by_ref(
            __import__("anerp.masterdata.models", fromlist=["Account"]).Account,
            payload.account_code,
            "Account",
        )
        return account_balance(ctx.session, payload.account_code, payload.as_of_date)


class PeriodCodePayload(_Strict):
    period_code: str | None = Field(default=None, description="YYYY-MM; omit for all periods")


@tool
class GetTrialBalance(QueryTool):
    name = "get_trial_balance"
    module = "query"
    scope = "finance:read"
    purpose = "Trial balance for a period (or all time): every account with debit/credit totals and is_balanced."
    payload_model = PeriodCodePayload

    def run(self, ctx: ToolContext, payload: PeriodCodePayload) -> dict[str, Any]:
        return trial_balance(ctx.session, payload.period_code)


class LedgerEntriesPayload(_Strict):
    account_code: str
    period_code: str | None = None
    limit: int = Field(default=200, ge=1, le=2000)


@tool
class GetLedgerEntries(QueryTool):
    name = "get_ledger_entries"
    module = "query"
    scope = "finance:read"
    purpose = (
        "Journal lines posted to one account (with entry number, date, memo and source document)."
    )
    payload_model = LedgerEntriesPayload

    def run(self, ctx: ToolContext, payload: LedgerEntriesPayload) -> dict[str, Any]:
        stmt = (
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.account_code == payload.account_code)
        )  # type: ignore[arg-type]
        if payload.period_code:
            stmt = stmt.where(JournalEntry.period_code == payload.period_code)
        rows = ctx.session.exec(
            stmt.order_by(JournalEntry.posting_date, JournalEntry.number).limit(payload.limit)
        ).all()  # type: ignore[arg-type]
        running = 0
        entries = []
        for line, je in rows:
            running += line.debit_cents - line.credit_cents
            entries.append(
                {
                    "entry": je.number,
                    "entry_id": je.id,
                    "posting_date": je.posting_date.isoformat(),
                    "memo": je.memo,
                    "source_type": je.source_type,
                    "source_id": je.source_id,
                    "status": je.status,
                    "debit_cents": line.debit_cents,
                    "credit_cents": line.credit_cents,
                    "running_net_cents": running,
                    "description": line.description,
                }
            )
        return {
            "account": payload.account_code,
            "period": payload.period_code,
            "count": len(entries),
            "entries": entries,
        }


class InventoryPayload(_Strict):
    sku: str | None = None


@tool
class GetInventory(QueryTool):
    name = "get_inventory"
    module = "query"
    scope = "inventory:read"
    purpose = "On-hand quantities and standard cost value for one SKU or all items."
    payload_model = InventoryPayload

    def run(self, ctx: ToolContext, payload: InventoryPayload) -> dict[str, Any]:
        stmt = select(Item).order_by(Item.sku)  # type: ignore[arg-type]
        if payload.sku:
            stmt = stmt.where(Item.sku == payload.sku)
        rows = ctx.session.exec(stmt).all()
        if payload.sku and not rows:
            raise not_found("Item", payload.sku)
        items = [
            {
                "sku": i.sku,
                "name": i.name,
                "is_stocked": i.is_stocked,
                "is_active": i.is_active,
                "on_hand_qty": i.on_hand_qty,
                "standard_cost_cents": i.standard_cost_cents,
                "list_price_cents": i.list_price_cents,
                "value_cents": i.on_hand_qty * i.standard_cost_cents,
            }
            for i in rows
        ]
        return {"items": items, "total_value_cents": sum(i["value_cents"] for i in items)}


class GetPeriodPayload(_Strict):
    period_code: str = Field(pattern=r"^\d{4}-\d{2}$")


@tool
class GetPeriod(QueryTool):
    name = "get_period"
    module = "query"
    scope = "finance:read"
    purpose = "Fiscal period status plus the close-readiness checklist (blockers and warnings)."
    payload_model = GetPeriodPayload

    def run(self, ctx: ToolContext, payload: GetPeriodPayload) -> dict[str, Any]:
        period = ctx.get_by_ref(FiscalPeriod, payload.period_code, "FiscalPeriod")
        return {
            "period": period.model_dump(mode="json"),
            "close_readiness": close_readiness(ctx.session, period),
        }


class PollEventsPayload(_Strict):
    after_seq: int = Field(default=0, ge=0)
    types: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=1000)


@tool
class PollEvents(QueryTool):
    name = "poll_events"
    module = "query"
    scope = "events:read"
    purpose = "Return events with seq greater than after_seq (optionally filtered by type). Agents poll this instead of scraping tables."
    payload_model = PollEventsPayload

    def run(self, ctx: ToolContext, payload: PollEventsPayload) -> dict[str, Any]:
        events = poll(ctx.session, payload.after_seq, payload.types, payload.limit)
        return {
            "events": events,
            "count": len(events),
            "last_seq": events[-1]["seq"] if events else payload.after_seq,
        }


class VerifyReceiptPayload(_Strict):
    receipt_id: str


@tool
class VerifyReceipt(QueryTool):
    name = "verify_receipt"
    module = "query"
    scope = "documents:read"
    purpose = "Recompute a receipt's action hash and verify its Ed25519 signature against the server's public key."
    payload_model = VerifyReceiptPayload

    def run(self, ctx: ToolContext, payload: VerifyReceiptPayload) -> dict[str, Any]:
        return verify_receipt(ctx.session, payload.receipt_id)


class DescribeToolPayload(_Strict):
    name: str


@tool
class DescribeTool(QueryTool):
    name = "describe_tool"
    module = "query"
    scope = "documents:read"
    purpose = "Long-form description, input schema, preconditions, effects and compensating tool for one tool (use it to plan)."
    payload_model = DescribeToolPayload

    def run(self, ctx: ToolContext, payload: DescribeToolPayload) -> dict[str, Any]:
        t = registry.get(payload.name)
        if t is None:
            raise not_found("Tool", payload.name)
        return {
            "name": t.name,
            "kind": t.kind,
            "module": t.module,
            "scope": t.scope,
            "description": t.description(),
            "input_schema": t.input_schema(),
            "preconditions": getattr(t, "preconditions", []),
            "effects": getattr(t, "effects", ""),
            "compensating_tool": getattr(t, "compensating_tool", None),
            "emits": getattr(t, "emits", []),
            "common_errors": getattr(t, "common_errors", []),
            "annotations": vars(t.annotations),
            "example_envelope": {
                "mode": "simulate",
                "idempotency_key": "<required on commit, 8-128 chars>",
                "payload": "<fields per input_schema>",
            },
        }


class EmptyQuery(_Strict):
    pass


@tool
class ListCapabilities(QueryTool):
    name = "list_capabilities"
    module = "query"
    scope = "documents:read"
    purpose = "Catalog of every tool grouped by module with required scope and a one-line summary."
    payload_model = EmptyQuery

    def run(self, ctx: ToolContext, payload: EmptyQuery) -> dict[str, Any]:
        return registry.catalog()
