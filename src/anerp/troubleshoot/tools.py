"""Troubleshooting tools (DESIGN.md §7.7): document flow, balance explanation, error forensics, recon."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlmodel import select

from anerp.approvals.models import ApprovalRequest
from anerp.core.context import ToolContext
from anerp.core.errors import AnerpError, ErrorCode, not_found, validation
from anerp.core.hashing import hash_obj
from anerp.core.ids import iso, utcnow
from anerp.core.registry import QueryTool, registry, tool
from anerp.core.requestlog import request_log
from anerp.documents import (
    base_dump,
    events_for,
    find_document,
    journal_dump,
    receipts_for,
    summary,
)
from anerp.events.models import Event
from anerp.finance.models import FiscalPeriod, JournalEntry, JournalLine, OpenItem
from anerp.ledger.models import Receipt
from anerp.ledger.receipts import receipt_to_dict
from anerp.ledger.trial_balance import account_balance
from anerp.masterdata.models import Item
from anerp.models import DOCUMENT_TYPES
from anerp.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierInvoice,
    SupplierPayment,
)
from anerp.sales.models import CreditNote, CustomerInvoice, CustomerPayment, SalesOrder, Shipment


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- trace_document ------------------------------------------------------------------
class TracePayload(_Strict):
    id_or_number: str


def _node(session: Any, type_name: str, row: Any) -> dict[str, Any]:
    node = summary(type_name, row)
    receipts = receipts_for(session, row.id)
    node["receipts"] = [
        {
            "id": r["id"],
            "tool": r["tool_name"],
            "actor": r["actor_id"],
            "on_behalf_of": r["on_behalf_of"],
            "signed_at": r["signed_at"],
        }
        for r in receipts
    ]
    node["event_seqs"] = [e["seq"] for e in events_for(session, row.id)]
    je_id = getattr(row, "journal_entry_id", None)
    if je_id:
        je = session.get(JournalEntry, je_id)
        if je is not None:
            node["journal_entry"] = {
                "number": je.number,
                "status": je.status,
                "posting_date": je.posting_date.isoformat(),
                "lines": journal_dump(session, je)["lines"],
                "reversed_by": journal_dump(session, je)["reversed_by"],
            }
    rev = getattr(row, "reversal_of_id", None)
    if rev:
        node["reversal_of_id"] = rev
    return node


def _root(session: Any, type_name: str, row: Any) -> tuple[str, Any]:
    """Walk up to the head document of the chain (PO or SO); other docs are their own root."""
    if type_name in ("GoodsReceipt", "SupplierInvoice"):
        po = session.get(PurchaseOrder, row.po_id)
        return ("PurchaseOrder", po) if po else (type_name, row)
    if type_name == "SupplierPayment":
        inv = session.get(SupplierInvoice, row.invoice_id)
        return _root(session, "SupplierInvoice", inv) if inv else (type_name, row)
    if type_name in ("Shipment", "CustomerInvoice"):
        so = session.get(SalesOrder, row.so_id)
        return ("SalesOrder", so) if so else (type_name, row)
    if type_name in ("CustomerPayment", "CreditNote"):
        inv = session.get(CustomerInvoice, row.invoice_id)
        return _root(session, "CustomerInvoice", inv) if inv else (type_name, row)
    if type_name == "JournalEntry" and row.source_id:
        found = find_document(session, row.source_id)
        if found and found[0] != "JournalEntry":
            return _root(session, *found)
    if type_name == "ApprovalRequest":
        found = find_document(session, row.document_id)
        if found:
            return _root(session, *found)
    return type_name, row


@tool
class TraceDocument(QueryTool):
    name = "trace_document"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "Full causal chain of a document (PO -> GRN -> SINV -> JE -> PAY, or SO -> SHP -> CINV -> RCPT/CN), each node with status, receipts, actors and event seqs; reversals included."
    payload_model = TracePayload

    def run(self, ctx: ToolContext, payload: TracePayload) -> dict[str, Any]:
        s = ctx.session
        found = find_document(s, payload.id_or_number)
        if found is None:
            raise not_found("Document", payload.id_or_number)
        root_type, root = _root(s, *found)
        chain: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []

        def add(
            type_name: str, row: Any, parent: Any | None = None, relation: str = ""
        ) -> dict[str, Any]:
            node = _node(s, type_name, row)
            chain.append(node)
            if parent is not None:
                edges.append({"from": parent.id, "to": row.id, "relation": relation})
            return node

        add(root_type, root)
        if root_type == "PurchaseOrder":
            for a in s.exec(
                select(ApprovalRequest).where(ApprovalRequest.document_id == root.id)
            ).all():
                add("ApprovalRequest", a, root, "approval")
            for g in s.exec(
                select(GoodsReceipt)
                .where(GoodsReceipt.po_id == root.id)
                .order_by(GoodsReceipt.created_at)
            ).all():  # type: ignore[arg-type]
                add("GoodsReceipt", g, root, "reversal" if g.reversal_of_id else "receipt")
            for inv in s.exec(
                select(SupplierInvoice)
                .where(SupplierInvoice.po_id == root.id)
                .order_by(SupplierInvoice.created_at)
            ).all():  # type: ignore[arg-type]
                add("SupplierInvoice", inv, root, "invoice")
                for pay in s.exec(
                    select(SupplierPayment).where(SupplierPayment.invoice_id == inv.id)
                ).all():
                    add("SupplierPayment", pay, inv, "payment")
        elif root_type == "SalesOrder":
            for sh in s.exec(
                select(Shipment).where(Shipment.so_id == root.id).order_by(Shipment.created_at)
            ).all():  # type: ignore[arg-type]
                add("Shipment", sh, root, "shipment")
            for inv in s.exec(
                select(CustomerInvoice)
                .where(CustomerInvoice.so_id == root.id)
                .order_by(CustomerInvoice.created_at)
            ).all():  # type: ignore[arg-type]
                add("CustomerInvoice", inv, root, "invoice")
                for pay in s.exec(
                    select(CustomerPayment).where(CustomerPayment.invoice_id == inv.id)
                ).all():
                    add("CustomerPayment", pay, inv, "payment")
                for cn in s.exec(select(CreditNote).where(CreditNote.invoice_id == inv.id)).all():
                    add("CreditNote", cn, inv, "credit_note")
        # reversal journal entries linked to any node's JE
        je_ids = [n["journal_entry"] for n in chain if n.get("journal_entry")]
        reversal_jes = []
        for n in chain:
            je = n.get("journal_entry")
            if je and je.get("reversed_by"):
                for num in je["reversed_by"]:
                    rj = s.exec(select(JournalEntry).where(JournalEntry.number == num)).first()
                    if rj is not None:
                        reversal_jes.append(
                            {
                                "number": rj.number,
                                "reversal_of": je["number"],
                                "memo": rj.memo,
                                "posting_date": rj.posting_date.isoformat(),
                                "lines": journal_dump(s, rj)["lines"],
                            }
                        )
        return {
            "requested": payload.id_or_number,
            "root": summary(root_type, root),
            "nodes": chain,
            "edges": edges,
            "reversal_journal_entries": reversal_jes,
            "journal_entry_count": len(je_ids),
        }


# ---- explain_balance ----------------------------------------------------------------
class ExplainBalancePayload(_Strict):
    account_code: str
    period_code: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


@tool
class ExplainBalance(QueryTool):
    name = "explain_balance"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "Movements behind an account balance grouped by source document, with the actor that caused each, running totals, and reversal pairs flagged."
    payload_model = ExplainBalancePayload

    def run(self, ctx: ToolContext, payload: ExplainBalancePayload) -> dict[str, Any]:
        s = ctx.session
        stmt = (
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.account_code == payload.account_code)
        )  # type: ignore[arg-type]
        if payload.period_code:
            stmt = stmt.where(JournalEntry.period_code == payload.period_code)
        rows = s.exec(stmt.order_by(JournalEntry.posting_date, JournalEntry.number)).all()  # type: ignore[arg-type]
        movements = []
        groups: dict[str, dict[str, Any]] = {}
        running = 0
        receipt_by_je = {}
        for line, je in rows:
            if je.receipt_id and je.receipt_id not in receipt_by_je:
                receipt_by_je[je.receipt_id] = s.get(Receipt, je.receipt_id)
            receipt = receipt_by_je.get(je.receipt_id) if je.receipt_id else None
            net = line.debit_cents - line.credit_cents
            running += net
            src = find_document(s, je.source_id) if je.source_id else None
            src_number = getattr(src[1], "number", None) if src else je.source_id
            movement = {
                "entry": je.number,
                "posting_date": je.posting_date.isoformat(),
                "source_type": je.source_type,
                "source": src_number,
                "memo": je.memo,
                "debit_cents": line.debit_cents,
                "credit_cents": line.credit_cents,
                "net_cents": net,
                "running_cents": running,
                "actor": receipt.actor_id if receipt else None,
                "on_behalf_of": receipt.on_behalf_of if receipt else None,
                "tool": receipt.tool_name if receipt else None,
                "is_reversal": je.reversal_of_id is not None,
                "reversal_of": None,
                "reversed": je.status == "reversed",
            }
            if je.reversal_of_id:
                orig = s.get(JournalEntry, je.reversal_of_id)
                movement["reversal_of"] = orig.number if orig else je.reversal_of_id
            movements.append(movement)
            g = groups.setdefault(
                je.source_type, {"source_type": je.source_type, "count": 0, "net_cents": 0}
            )
            g["count"] += 1
            g["net_cents"] += net
        bal = account_balance(s, payload.account_code)
        pairs = [
            {"original": m["reversal_of"], "reversal": m["entry"]}
            for m in movements
            if m["reversal_of"]
        ]
        return {
            "account": payload.account_code,
            "period": payload.period_code,
            "balance": bal,
            "by_source_type": list(groups.values()),
            "movements": movements,
            "reversal_pairs": pairs,
        }


# ---- explain_error -------------------------------------------------------------------
class ExplainErrorPayload(_Strict):
    request_id: str


@tool
class ExplainError(QueryTool):
    name = "explain_error"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "For a failed or denied request id: the redacted envelope, error code, policy rules evaluated with reasons, and the state versions at that time."
    payload_model = ExplainErrorPayload

    def run(self, ctx: ToolContext, payload: ExplainErrorPayload) -> dict[str, Any]:
        entry = request_log.get(payload.request_id)
        if entry is None:
            raise not_found("request", payload.request_id)
        d = entry.as_dict()
        d["explanation"] = _explain(entry)
        return d


def _explain(entry: Any) -> str:
    if entry.outcome in ("applied", "replayed", "simulated", "ok"):
        return f"request {entry.request_id} succeeded ({entry.outcome}); nothing to explain"
    code = entry.error_code or "UNKNOWN"
    parts = [
        f"{entry.tool} in mode {entry.mode} by {entry.actor_id} failed with {code}: {entry.error_message}"
    ]
    if entry.policy and entry.policy.get("reasons"):
        parts.append("policy reasons: " + "; ".join(entry.policy["reasons"]))
    if entry.policy and entry.policy.get("rules_evaluated"):
        parts.append("rules evaluated: " + ", ".join(entry.policy["rules_evaluated"]))
    return " | ".join(parts)


# ---- replay_simulate -----------------------------------------------------------------
class ReplayPayload(_Strict):
    receipt_id: str


@tool
class ReplaySimulate(QueryTool):
    name = "replay_simulate"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "Re-run a receipt's original payload in simulate mode against current state and diff the projection against the original. Never commits. Requires the original tool's write scope."
    payload_model = ReplayPayload

    def run(self, ctx: ToolContext, payload: ReplayPayload) -> dict[str, Any]:
        from anerp.core.dispatch import dispatch
        from anerp.core.envelope import Actor, Envelope

        receipt = ctx.session.get(Receipt, payload.receipt_id)
        if receipt is None:
            raise not_found("Receipt", payload.receipt_id)
        original_tool = registry.get(receipt.tool_name)
        if original_tool is None:
            raise not_found("Tool", receipt.tool_name)
        if ctx.principal is not None and not ctx.principal.has_scope(original_tool.scope):
            raise AnerpError(
                ErrorCode.FORBIDDEN,
                f"replay requires scope {original_tool.scope}",
                {"required_scope": original_tool.scope},
            )
        env = Envelope(
            tool=receipt.tool_name,
            mode="simulate",
            actor=Actor(id=ctx.actor.id, kind=ctx.actor.kind, on_behalf_of=f"replay:{receipt.id}"),
            payload=receipt.payload_json,
        )
        now = dispatch(env)
        original = receipt.projection_json
        current = now.get("projected_effects") if now.get("ok") else None
        return {
            "receipt_id": receipt.id,
            "tool": receipt.tool_name,
            "original_actor": receipt.actor_id,
            "original_projection": original,
            "current_simulation": now,
            "diff": _diff(original, current),
            "identical": _diff(original, current) == [],
        }


def _diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ("id", "number", "fields", "expires_at"):
                continue
            out.extend(_diff(a.get(k), b.get(k), f"{path}.{k}" if path else k))
    elif isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            out.extend(_diff(x, y, f"{path}[{i}]"))
        if len(a) != len(b):
            out.append({"path": path, "original_len": len(a), "current_len": len(b)})
    elif a != b:
        out.append({"path": path, "original": a, "current": b})
    return out


# ---- find_duplicates ------------------------------------------------------------------
class DuplicatesPayload(_Strict):
    document_type: Literal[
        "PurchaseOrder",
        "SalesOrder",
        "SupplierInvoice",
        "CustomerInvoice",
        "SupplierPayment",
        "CustomerPayment",
    ] = "PurchaseOrder"
    window_minutes: int = Field(default=60, ge=1, le=60 * 24 * 30)


@tool
class FindDuplicates(QueryTool):
    name = "find_duplicates"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "Documents with identical party, lines and amounts created within a time window, with their idempotency keys and actors (the duplicate-PO investigation)."
    payload_model = DuplicatesPayload

    def run(self, ctx: ToolContext, payload: DuplicatesPayload) -> dict[str, Any]:
        s = ctx.session
        model = DOCUMENT_TYPES[payload.document_type]
        rows = s.exec(select(model).order_by(model.created_at)).all()  # type: ignore[attr-defined]
        fingerprints: dict[str, list[Any]] = {}
        for row in rows:
            fp = _fingerprint(s, payload.document_type, row)
            fingerprints.setdefault(fp, []).append(row)
        groups = []
        window = timedelta(minutes=payload.window_minutes)
        for fp, items in fingerprints.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda r: r.created_at)
            cluster: list[Any] = []
            for row in items:
                if cluster and (row.created_at - cluster[0].created_at) > window:
                    if len(cluster) > 1:
                        groups.append(_dup_group(s, payload.document_type, fp, cluster))
                    cluster = []
                cluster.append(row)
            if len(cluster) > 1:
                groups.append(_dup_group(s, payload.document_type, fp, cluster))
        return {
            "document_type": payload.document_type,
            "window_minutes": payload.window_minutes,
            "groups": groups,
            "count": len(groups),
        }


def _fingerprint(s: Any, type_name: str, row: Any) -> str:
    data: dict[str, Any] = {
        "party": getattr(row, "supplier_id", None) or getattr(row, "customer_id", None),
        "total": getattr(row, "total_cents", None) or getattr(row, "amount_cents", None),
    }
    if type_name == "PurchaseOrder":
        data["lines"] = [
            (line.sku, line.qty, line.unit_cost_cents)
            for line in s.exec(
                select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == row.id)
            ).all()
        ]
    elif type_name == "SalesOrder":
        from anerp.sales.models import SalesOrderLine

        data["lines"] = [
            (line.sku, line.qty, line.unit_price_cents)
            for line in s.exec(select(SalesOrderLine).where(SalesOrderLine.so_id == row.id)).all()
        ]
    elif hasattr(row, "lines"):
        data["lines"] = [
            (
                line.get("sku"),
                line.get("invoice_qty") or line.get("qty"),
                line.get("invoice_unit_cost_cents") or line.get("unit_price_cents"),
            )
            for line in row.lines
        ]
    if hasattr(row, "invoice_id"):
        data["invoice_id"] = row.invoice_id
    return hash_obj(data)


def _dup_group(s: Any, type_name: str, fp: str, rows: list[Any]) -> dict[str, Any]:
    docs = []
    for row in rows:
        receipts = s.exec(
            select(Receipt).where(Receipt.document_id == row.id).order_by(Receipt.signed_at)
        ).all()  # type: ignore[arg-type]
        first = receipts[0] if receipts else None
        docs.append(
            {
                **summary(type_name, row),
                "idempotency_key": first.idempotency_key if first else None,
                "actor": first.actor_id if first else None,
                "on_behalf_of": first.on_behalf_of if first else None,
            }
        )
    return {
        "fingerprint": fp,
        "count": len(rows),
        "documents": docs,
        "span_seconds": (rows[-1].created_at - rows[0].created_at).total_seconds(),
    }


# ---- get_reconciliation --------------------------------------------------------------
class ReconPayload(_Strict):
    kind: Literal["gr_ir", "ap", "ar", "inventory"]


@tool
class GetReconciliation(QueryTool):
    name = "get_reconciliation"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "gr_ir: open GR/IR by PO (received vs invoiced); ap/ar: sub-ledger open items vs control account 2000/1200; inventory: on-hand x standard cost vs account 1300."
    payload_model = ReconPayload

    def run(self, ctx: ToolContext, payload: ReconPayload) -> dict[str, Any]:
        s = ctx.session
        if payload.kind == "gr_ir":
            lines = s.exec(
                select(PurchaseOrderLine, PurchaseOrder)
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id)
                .where(PurchaseOrderLine.received_qty != PurchaseOrderLine.invoiced_qty)
            ).all()  # type: ignore[arg-type]
            by_po: dict[str, dict[str, Any]] = {}
            for line, po in lines:
                g = by_po.setdefault(
                    po.number, {"po": po.number, "status": po.status, "lines": [], "open_cents": 0}
                )
                open_c = (line.received_qty - line.invoiced_qty) * line.unit_cost_cents
                g["lines"].append(
                    {
                        "sku": line.sku,
                        "received_qty": line.received_qty,
                        "invoiced_qty": line.invoiced_qty,
                        "unit_cost_cents": line.unit_cost_cents,
                        "open_cents": open_c,
                    }
                )
                g["open_cents"] += open_c
            sub = sum(g["open_cents"] for g in by_po.values())
            gl = account_balance(s, "1400")
            return {
                "kind": "gr_ir",
                "by_po": list(by_po.values()),
                "subledger_open_cents": sub,
                "gl_1400_net_cents": gl["net_cents"],
                "difference_cents": -gl["net_cents"] - sub,
                "reconciled": -gl["net_cents"] == sub,
            }
        if payload.kind in ("ap", "ar"):
            control = "2000" if payload.kind == "ap" else "1200"
            open_items = s.exec(
                select(OpenItem).where(
                    OpenItem.kind == payload.kind, OpenItem.status.in_(["open", "partially_paid"])
                )
            ).all()  # type: ignore[attr-defined]
            sub = sum(o.remaining_cents for o in open_items)
            gl = account_balance(s, control)
            gl_net = -gl["net_cents"] if payload.kind == "ap" else gl["net_cents"]
            return {
                "kind": payload.kind,
                "control_account": control,
                "open_items": [base_dump(o) for o in open_items],
                "subledger_cents": sub,
                "control_account_cents": gl_net,
                "difference_cents": gl_net - sub,
                "reconciled": gl_net == sub,
            }
        items = s.exec(select(Item).where(Item.is_stocked == True)).all()  # noqa: E712
        value = sum(i.on_hand_qty * i.standard_cost_cents for i in items)
        gl = account_balance(s, "1300")
        return {
            "kind": "inventory",
            "items": [
                {
                    "sku": i.sku,
                    "on_hand_qty": i.on_hand_qty,
                    "standard_cost_cents": i.standard_cost_cents,
                    "value_cents": i.on_hand_qty * i.standard_cost_cents,
                }
                for i in items
            ],
            "subledger_value_cents": value,
            "gl_1300_net_cents": gl["net_cents"],
            "difference_cents": gl["net_cents"] - value,
            "reconciled": gl["net_cents"] == value,
            "note": "differences arise from purchase price variance postings and non-standard receipt costs",
        }


# ---- get_agent_activity / get_request_log ---------------------------------------------
class ActivityPayload(_Strict):
    actor_id: str
    since: datetime | None = None
    limit: int = Field(default=200, ge=1, le=2000)


@tool
class GetAgentActivity(QueryTool):
    name = "get_agent_activity"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "Everything one actor did: commits (with receipts), simulates, denials and error codes, plus counts."
    payload_model = ActivityPayload

    def run(self, ctx: ToolContext, payload: ActivityPayload) -> dict[str, Any]:
        entries = request_log.query(
            since=payload.since, actor=payload.actor_id, limit=payload.limit
        )
        receipts = ctx.session.exec(
            select(Receipt)
            .where(Receipt.actor_id == payload.actor_id)
            .order_by(Receipt.signed_at.desc())
            .limit(payload.limit)
        ).all()  # type: ignore[attr-defined]
        counts: dict[str, int] = {}
        errors: dict[str, int] = {}
        for e in entries:
            counts[e.outcome] = counts.get(e.outcome, 0) + 1
            if e.error_code:
                errors[e.error_code] = errors.get(e.error_code, 0) + 1
        return {
            "actor_id": payload.actor_id,
            "counts": counts,
            "error_codes": errors,
            "requests": [e.as_dict() for e in entries],
            "receipts": [receipt_to_dict(r) for r in receipts],
        }


class RequestLogPayload(_Strict):
    since: datetime | None = None
    actor: str | None = None
    tool: str | None = None
    error_code: str | None = None
    mode: Literal["simulate", "commit", "query"] | None = None
    limit: int = Field(default=100, ge=1, le=2000)
    offset: int = Field(default=0, ge=0)


@tool
class GetRequestLog(QueryTool):
    name = "get_request_log"
    module = "troubleshoot"
    scope = "troubleshoot:read"
    purpose = "Paged request log (tool, mode, actor, outcome, latency, request_id), newest first. In-memory for this process."
    payload_model = RequestLogPayload

    def run(self, ctx: ToolContext, payload: RequestLogPayload) -> dict[str, Any]:
        entries = request_log.query(
            since=payload.since,
            actor=payload.actor,
            tool=payload.tool,
            error_code=payload.error_code,
            mode=payload.mode,
            limit=payload.limit,
            offset=payload.offset,
        )
        return {
            "count": len(entries),
            "offset": payload.offset,
            "requests": [e.as_dict() for e in entries],
        }


__all__ = ["Event", "FiscalPeriod", "func", "iso", "utcnow", "validation"]
