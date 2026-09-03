"""Procure-to-pay tools (DESIGN.md §7.2)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from anerp.approvals.models import ApprovalRequest
from anerp.core.context import ToolContext
from anerp.core.errors import validation
from anerp.core.ids import utcnow
from anerp.core.money import Money, PositiveMoney, Qty, cents, fmt
from anerp.core.projection import (
    Compensation,
    DocumentEffect,
    EventSpec,
    InventoryDelta,
    JournalSpec,
    LineSpec,
    Projection,
)
from anerp.core.registry import Annotations, WriteTool, tool
from anerp.finance.models import OpenItem
from anerp.masterdata.models import Item, Supplier
from anerp.procurement.matching import MatchLine, MatchResult
from anerp.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierInvoice,
    SupplierPayment,
)

ACCT_CASH = "1000"
ACCT_INVENTORY = "1300"
ACCT_GRIR = "1400"
ACCT_AP = "2000"
ACCT_OPEX = "5100"
ACCT_PPV = "5200"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _today() -> date:
    return utcnow().date()


def _po_lines(ctx: ToolContext, po: PurchaseOrder) -> list[PurchaseOrderLine]:
    lines = ctx.session.exec(
        select(PurchaseOrderLine)
        .where(PurchaseOrderLine.po_id == po.id)
        .order_by(PurchaseOrderLine.line_no)  # type: ignore[arg-type]
    ).all()
    for line in lines:
        ctx.touch(line)
    return list(lines)


def _po_status_after(
    lines: list[PurchaseOrderLine], received: dict[str, int], invoiced: dict[str, int]
) -> str:
    """Derive PO status from projected per-line received/invoiced quantities."""
    total = sum(line.qty for line in lines)
    total_received = sum(received.get(line.id, line.received_qty) for line in lines)
    total_invoiced = sum(invoiced.get(line.id, line.invoiced_qty) for line in lines)
    if total_invoiced >= total and total > 0:
        return "invoiced"
    if total_received >= total and total > 0:
        return "received"
    if total_received > 0:
        return "partially_received"
    return "approved"


def _po_facts(po: PurchaseOrder, lines: list[PurchaseOrderLine]) -> dict[str, Any]:
    return {
        "id": po.id,
        "number": po.number,
        "status": po.status,
        "total_cents": po.total_cents,
        "created_by": po.created_by,
        "supplier_id": po.supplier_id,
        "line_count": len(lines),
    }


# ======================================================================================
# create_purchase_order
# ======================================================================================
class POLineInput(_Strict):
    sku: str = Field(description="Item SKU")
    qty: Qty
    unit_cost: Money = Field(description="Agreed unit cost, e.g. 50.00")


class CreatePOPayload(_Strict):
    supplier: str = Field(description="Supplier code or id, e.g. ACME")
    lines: list[POLineInput] = Field(min_length=1)
    memo: str = ""


@tool
class CreatePurchaseOrder(WriteTool):
    name = "create_purchase_order"
    module = "procurement"
    scope = "procurement:write"
    purpose = "Raise a purchase order with a supplier for one or more items at agreed unit costs."
    preconditions = [
        "supplier is active",
        "every item is active",
        "qty > 0 and unit_cost >= 0 per line",
    ]
    effects = (
        "PurchaseOrder created in status 'approved' when under the approval threshold, otherwise "
        "'draft' with an ApprovalRequest for a human approver; GL: none; inventory: none; "
        "events: purchase_order.created (+ approval.requested)."
    )
    compensating_tool = "cancel_purchase_order"
    compensating_when = "before any goods are received"
    common_errors = [
        "NOT_FOUND for unknown supplier/sku",
        "PRECONDITION_FAILED when supplier or item is inactive",
        "policy po_approval_threshold -> requires_approval (PO stays draft until approve_purchase_order)",
    ]
    emits = ["purchase_order.created", "approval.requested"]
    payload_model = CreatePOPayload
    annotations = Annotations(destructive=False)

    def project(self, ctx: ToolContext, payload: CreatePOPayload) -> Projection:
        supplier = ctx.get_by_ref(Supplier, payload.supplier, "Supplier")
        ctx.require_active(supplier, "Supplier")
        po = PurchaseOrder(
            number=ctx.number_for("PurchaseOrder"),
            supplier_id=supplier.id,
            status="approved",
            memo=payload.memo,
            created_by=ctx.actor.id,
            approved_by="policy:auto",
            approved_at=ctx.now,
        )
        p = Projection()
        p.create("PurchaseOrder", po, primary=True)
        total = 0
        seen: set[str] = set()
        for i, line in enumerate(payload.lines, start=1):
            item = ctx.get_by_ref(Item, line.sku, "Item")
            ctx.require_active(item, "Item")
            if item.sku in seen:
                raise validation(f"sku {item.sku} appears twice; merge the lines", sku=item.sku)
            seen.add(item.sku)
            unit_cost = cents(line.unit_cost)
            total += unit_cost * line.qty
            p.create(
                "PurchaseOrderLine",
                PurchaseOrderLine(
                    po_id=po.id,
                    line_no=i,
                    item_id=item.id,
                    sku=item.sku,
                    qty=line.qty,
                    unit_cost_cents=unit_cost,
                ),
            )
        po.total_cents = total
        p.facts = {"po": _po_facts(po, [d.instance for d in p.documents[1:]])}  # type: ignore[misc]
        p.extra = {"total": fmt(total), "supplier": {"code": supplier.code, "name": supplier.name}}
        p.events.append(
            EventSpec(
                "purchase_order.created", f"PO {po.number} for {supplier.code} total {fmt(total)}"
            )
        )
        p.compensation = Compensation("cancel_purchase_order", {"po": po.number})

        def downgrade() -> None:
            po.status = "draft"
            po.approved_by = None
            po.approved_at = None

        p.on_requires_approval = downgrade
        p.approval_reason = f"PO total {fmt(total)} exceeds the approval threshold"
        return p


# ======================================================================================
# approve_purchase_order
# ======================================================================================
class ApprovePOPayload(_Strict):
    po: str = Field(description="PO number or id")
    comment: str = ""


@tool
class ApprovePurchaseOrder(WriteTool):
    name = "approve_purchase_order"
    module = "procurement"
    scope = "procurement:approve"
    purpose = (
        "Approve a draft purchase order so goods can be received against it (human approvers only)."
    )
    preconditions = [
        "PO status is draft",
        "actor is not the PO creator (four-eyes)",
        "actor token kind is human or admin",
    ]
    effects = "PO -> approved; pending ApprovalRequest -> approved; GL: none; events: purchase_order.approved, approval.approved."
    compensating_tool = "cancel_purchase_order"
    compensating_when = "before goods are received"
    common_errors = [
        "PRECONDITION_FAILED if not draft",
        "POLICY_DENIED for self-approval or agent tokens",
    ]
    emits = ["purchase_order.approved", "approval.approved"]
    payload_model = ApprovePOPayload

    def project(self, ctx: ToolContext, payload: ApprovePOPayload) -> Projection:
        po = ctx.get_by_ref(PurchaseOrder, payload.po, "PurchaseOrder")
        ctx.require(
            po.status == "draft", f"PO {po.number} is {po.status}, not draft", status=po.status
        )
        lines = _po_lines(ctx, po)
        p = Projection()
        p.update(
            "PurchaseOrder",
            po,
            {"status": "approved", "approved_by": ctx.actor.id, "approved_at": ctx.now},
            primary=True,
        )
        for req in ctx.find(ApprovalRequest, document_id=po.id, status="pending"):
            ctx.touch(req)
            p.update(
                "ApprovalRequest",
                req,
                {
                    "status": "approved",
                    "decided_by": ctx.actor.id,
                    "decided_at": ctx.now,
                    "decision_comment": payload.comment,
                },
            )
            p.events.append(
                EventSpec(
                    "approval.approved",
                    f"Approval request {req.id} approved by {ctx.actor.id}",
                    "ApprovalRequest",
                    req,
                )
            )
        p.facts = {"po": _po_facts(po, lines)}
        p.events.insert(
            0, EventSpec("purchase_order.approved", f"PO {po.number} approved by {ctx.actor.id}")
        )
        p.compensation = Compensation("cancel_purchase_order", {"po": po.number})
        return p


# ======================================================================================
# receive_goods
# ======================================================================================
class ReceiptLineInput(_Strict):
    sku: str
    qty: Qty


class ReceiveGoodsPayload(_Strict):
    po: str = Field(description="PO number or id")
    lines: list[ReceiptLineInput] | None = Field(
        default=None, description="Omit to receive everything outstanding"
    )
    posting_date: date | None = Field(default=None, description="Defaults to today")


@tool
class ReceiveGoods(WriteTool):
    name = "receive_goods"
    module = "procurement"
    scope = "procurement:write"
    purpose = "Record goods received against an approved purchase order; books inventory and GR/IR clearing at PO cost."
    preconditions = [
        "PO status approved or partially_received",
        "qty per line <= outstanding qty",
        "posting date in an open period",
    ]
    effects = (
        "GoodsReceipt created; GL: Dr 1300 Inventory (stocked) or 5100 Operating expense (non-stocked) / "
        "Cr 1400 GR/IR at PO unit cost; inventory: on_hand += qty; PO lines received_qty updated and PO status "
        "-> partially_received/received; events: goods.received."
    )
    compensating_tool = "reverse_goods_receipt"
    compensating_when = "while the receipt is not yet invoiced and stock is still on hand"
    common_errors = ["PRECONDITION_FAILED for wrong status or over-receipt", "PERIOD_CLOSED"]
    emits = ["goods.received"]
    payload_model = ReceiveGoodsPayload

    def project(self, ctx: ToolContext, payload: ReceiveGoodsPayload) -> Projection:
        po = ctx.get_by_ref(PurchaseOrder, payload.po, "PurchaseOrder")
        ctx.require(
            po.status in ("approved", "partially_received"),
            f"PO {po.number} is {po.status}; goods can only be received against approved or partially_received POs",
            status=po.status,
        )
        posting_date = payload.posting_date or _today()
        lines = _po_lines(ctx, po)
        by_sku = {line.sku: line for line in lines}
        requested = payload.lines or [
            ReceiptLineInput(sku=line.sku, qty=line.qty - line.received_qty)
            for line in lines
            if line.qty > line.received_qty
        ]
        ctx.require(bool(requested), f"PO {po.number} has nothing outstanding to receive")
        p = Projection()
        grn = GoodsReceipt(number=ctx.number_for("GoodsReceipt"), po_id=po.id, received_at=ctx.now)
        p.create("GoodsReceipt", grn, primary=True)
        journal_lines: list[LineSpec] = []
        grn_lines: list[dict[str, Any]] = []
        received_after: dict[str, int] = {}
        total = 0
        grir_total = 0
        for req in requested:
            line = by_sku.get(req.sku)
            if line is None:
                raise validation(f"sku {req.sku} is not on PO {po.number}", sku=req.sku)
            outstanding = line.qty - line.received_qty
            ctx.require(
                req.qty <= outstanding,
                f"cannot receive {req.qty} of {req.sku}: only {outstanding} outstanding",
                sku=req.sku,
                outstanding=outstanding,
            )
            item = ctx.get(Item, line.item_id, "Item")
            value = line.unit_cost_cents * req.qty
            total += value
            grir_total += value
            debit_acct = ACCT_INVENTORY if item.is_stocked else ACCT_OPEX
            journal_lines.append(
                LineSpec(
                    debit_acct,
                    debit_cents=value,
                    description=f"GRN {req.qty} x {item.sku} @ {fmt(line.unit_cost_cents)}",
                )
            )
            if item.is_stocked:
                p.inventory.append(InventoryDelta(item, item.sku, req.qty))
            received_after[line.id] = line.received_qty + req.qty
            p.update("PurchaseOrderLine", line, {"received_qty": line.received_qty + req.qty})
            grn_lines.append(
                {
                    "po_line_id": line.id,
                    "sku": item.sku,
                    "qty": req.qty,
                    "unit_cost_cents": line.unit_cost_cents,
                    "account": debit_acct,
                }
            )
        journal_lines.append(
            LineSpec(ACCT_GRIR, credit_cents=grir_total, description=f"GR/IR for PO {po.number}")
        )
        grn.lines = grn_lines
        grn.total_cents = total
        p.journal = JournalSpec(
            posting_date,
            f"Goods receipt {grn.number} for PO {po.number}",
            "GoodsReceipt",
            grn.id,
            journal_lines,
        )
        grn.journal_entry_id = p.journal.id
        new_status = _po_status_after(lines, received_after, {})
        p.update("PurchaseOrder", po, {"status": new_status})
        p.facts = {
            "po": _po_facts(po, lines),
            "grn": {"total_cents": total},
            **ctx.period_facts(posting_date),
        }
        p.events.append(
            EventSpec(
                "goods.received",
                f"GRN {grn.number}: received {fmt(total)} against PO {po.number}; PO now {new_status}",
            )
        )
        p.compensation = Compensation("reverse_goods_receipt", {"grn": grn.number})
        return p


# ======================================================================================
# post_supplier_invoice
# ======================================================================================
class InvoiceLineInput(_Strict):
    sku: str
    qty: Qty
    unit_cost: Money = Field(description="Unit cost on the supplier's invoice")


class PostSupplierInvoicePayload(_Strict):
    po: str = Field(description="PO number or id")
    supplier_reference: str = Field(default="", description="The supplier's own invoice number")
    lines: list[InvoiceLineInput] = Field(min_length=1)
    posting_date: date | None = None
    park_if_blocked: bool = Field(
        default=False,
        description="If the match fails tolerance, park the invoice as 'blocked' (no GL, no AP) instead of refusing",
    )


@tool
class PostSupplierInvoice(WriteTool):
    name = "post_supplier_invoice"
    module = "procurement"
    scope = "finance:ap:write"
    purpose = "Post a supplier invoice against a purchase order with three-way match (PO price/qty vs received qty vs invoice)."
    preconditions = [
        "PO has goods receipts",
        "invoice qty per line <= received qty minus already invoiced qty",
        "price variance within tolerance (2% or 50.00 per unit) unless park_if_blocked",
        "posting date in an open period",
    ]
    effects = (
        "SupplierInvoice created (match_status matched | variance_within_tolerance | blocked); GL: Dr 1400 GR/IR at PO cost "
        "[+ Dr/Cr 5200 Purchase price variance] / Cr 2000 Accounts payable at invoice amount; AP OpenItem created with due date "
        "from supplier terms; PO lines invoiced_qty updated and PO -> invoiced when fully invoiced; events: supplier_invoice.posted. "
        "A parked (blocked) invoice has no GL or AP effect."
    )
    compensating_tool = "reverse_supplier_invoice"
    compensating_when = "while unpaid and the period is open"
    common_errors = [
        "MATCH_VARIANCE_EXCEEDED (qty over receipt or price outside tolerance)",
        "PERIOD_CLOSED",
        "PRECONDITION_FAILED when nothing was received",
    ]
    emits = ["supplier_invoice.posted"]
    payload_model = PostSupplierInvoicePayload

    def project(self, ctx: ToolContext, payload: PostSupplierInvoicePayload) -> Projection:
        po = ctx.get_by_ref(PurchaseOrder, payload.po, "PurchaseOrder")
        supplier = ctx.get(Supplier, po.supplier_id, "Supplier")
        lines = _po_lines(ctx, po)
        ctx.require(
            po.status not in ("draft", "cancelled", "closed"),
            f"PO {po.number} is {po.status}",
            status=po.status,
        )
        ctx.require(
            any(line.received_qty > 0 for line in lines),
            f"PO {po.number} has no goods receipts yet; receive goods first",
        )
        posting_date = payload.posting_date or _today()
        by_sku = {line.sku: line for line in lines}
        match = MatchResult()
        for req in payload.lines:
            line = by_sku.get(req.sku)
            if line is None:
                raise validation(f"sku {req.sku} is not on PO {po.number}", sku=req.sku)
            match.lines.append(
                MatchLine(
                    po_line=line,
                    sku=req.sku,
                    invoice_qty=req.qty,
                    invoice_unit_cost_cents=cents(req.unit_cost),
                    po_unit_cost_cents=line.unit_cost_cents,
                    received_qty=line.received_qty,
                    already_invoiced_qty=line.invoiced_qty,
                )
            )
        grns = [g for g in ctx.find(GoodsReceipt, po_id=po.id) if g.status == "posted"]
        invoice = SupplierInvoice(
            number=ctx.number_for("SupplierInvoice"),
            supplier_id=supplier.id,
            po_id=po.id,
            grn_ids=[g.id for g in grns],
            supplier_reference=payload.supplier_reference,
            lines=[m.as_dict() for m in match.lines],
            total_cents=match.invoice_value_cents,
            variance_cents=match.variance_cents,
            posting_date=posting_date.isoformat(),
        )
        p = Projection()
        p.create("SupplierInvoice", invoice, primary=True)
        facts_match = match.facts()
        # Tolerance decision is made by policy; here we only compute what the tool needs to project.
        settings_tol_pct, settings_tol_abs = _tolerances()
        outside = (
            match.max_variance_pct > settings_tol_pct
            or abs(match.variance_cents) > settings_tol_abs
            or match.qty_exceeded
        )
        parked = outside and payload.park_if_blocked
        facts_match["parked"] = parked
        p.facts = {
            "po": _po_facts(po, lines),
            "match": facts_match,
            "invoice": {"total_cents": invoice.total_cents},
            **ctx.period_facts(posting_date),
        }
        p.extra = {
            "three_way_match": facts_match,
            "tolerance": {"pct": settings_tol_pct, "abs_cents": settings_tol_abs},
        }
        if parked:
            invoice.match_status = "blocked"
            invoice.status = "blocked"
            p.warnings.append(
                "invoice parked as blocked: no GL posting, no AP open item; resolve the variance then reverse and re-post"
            )
            p.events.append(
                EventSpec(
                    "supplier_invoice.blocked",
                    f"SINV {invoice.number} parked (blocked) for PO {po.number}: variance {fmt(match.variance_cents)}",
                )
            )
            p.compensation = Compensation("reverse_supplier_invoice", {"invoice": invoice.number})
            return p
        invoice.match_status = (
            "variance_within_tolerance" if match.variance_cents != 0 else "matched"
        )
        journal_lines = [
            LineSpec(
                ACCT_GRIR,
                debit_cents=match.po_value_cents,
                description=f"clear GR/IR for PO {po.number}",
            )
        ]
        if match.variance_cents > 0:
            journal_lines.append(
                LineSpec(
                    ACCT_PPV,
                    debit_cents=match.variance_cents,
                    description="purchase price variance",
                )
            )
        elif match.variance_cents < 0:
            journal_lines.append(
                LineSpec(
                    ACCT_PPV,
                    credit_cents=-match.variance_cents,
                    description="purchase price variance (favourable)",
                )
            )
        journal_lines.append(
            LineSpec(
                ACCT_AP,
                credit_cents=match.invoice_value_cents,
                description=f"AP {supplier.code} {payload.supplier_reference}".strip(),
            )
        )
        p.journal = JournalSpec(
            posting_date,
            f"Supplier invoice {invoice.number} ({supplier.code} {payload.supplier_reference})".strip(),
            "SupplierInvoice",
            invoice.id,
            journal_lines,
        )
        invoice.journal_entry_id = p.journal.id
        open_item = OpenItem(
            kind="ap",
            party_id=supplier.id,
            source_doc_type="SupplierInvoice",
            source_doc_id=invoice.id,
            source_doc_number=invoice.number,
            amount_cents=match.invoice_value_cents,
            remaining_cents=match.invoice_value_cents,
            due_date=posting_date + timedelta(days=supplier.payment_terms_days),
        )
        invoice.open_item_id = open_item.id
        p.open_items.append(DocumentEffect("OpenItem", "create", open_item))
        invoiced_after: dict[str, int] = {}
        for m in match.lines:
            invoiced_after[m.po_line.id] = m.already_invoiced_qty + m.invoice_qty
            p.update(
                "PurchaseOrderLine",
                m.po_line,
                {"invoiced_qty": m.already_invoiced_qty + m.invoice_qty},
            )
        new_status = _po_status_after(lines, {}, invoiced_after)
        if new_status != po.status:
            p.update("PurchaseOrder", po, {"status": new_status})
        p.extra["due_date"] = open_item.due_date.isoformat()
        p.events.append(
            EventSpec(
                "supplier_invoice.posted",
                f"SINV {invoice.number} posted for PO {po.number}: {fmt(invoice.total_cents)} ({invoice.match_status})",
            )
        )
        p.compensation = Compensation("reverse_supplier_invoice", {"invoice": invoice.number})
        return p


def _tolerances() -> tuple[float, int]:
    from anerp.policy.engine import get_engine

    params = get_engine().policy.params
    return float(params.get("price_tolerance_pct", 2.0)), int(
        params.get("price_tolerance_abs_cents", 5000)
    )


# ======================================================================================
# pay_supplier
# ======================================================================================
class PaySupplierPayload(_Strict):
    invoice: str = Field(description="Supplier invoice number (SINV-…) or id")
    amount: PositiveMoney | None = Field(
        default=None, description="Defaults to the remaining balance"
    )
    posting_date: date | None = None


@tool
class PaySupplier(WriteTool):
    name = "pay_supplier"
    module = "procurement"
    scope = "finance:ap:pay"
    purpose = "Pay a posted supplier invoice (fully or partially) from cash."
    preconditions = [
        "invoice AP open item remaining > 0",
        "amount <= remaining",
        "posting date in an open period",
    ]
    effects = "SupplierPayment created; GL: Dr 2000 Accounts payable / Cr 1000 Cash; AP OpenItem remaining -= amount (paid when 0); invoice -> paid when settled; events: supplier_payment.recorded."
    compensating_tool = "reverse_supplier_payment"
    compensating_when = "while the period is open"
    common_errors = ["PRECONDITION_FAILED when overpaying or invoice not open", "PERIOD_CLOSED"]
    emits = ["supplier_payment.recorded"]
    payload_model = PaySupplierPayload

    def project(self, ctx: ToolContext, payload: PaySupplierPayload) -> Projection:
        invoice = ctx.get_by_ref(SupplierInvoice, payload.invoice, "SupplierInvoice")
        ctx.require(
            invoice.status in ("posted",),
            f"invoice {invoice.number} is {invoice.status}",
            status=invoice.status,
        )
        assert invoice.open_item_id
        open_item = ctx.get(OpenItem, invoice.open_item_id, "OpenItem")
        ctx.require(
            open_item.remaining_cents > 0, f"invoice {invoice.number} has nothing outstanding"
        )
        amount = cents(payload.amount) if payload.amount is not None else open_item.remaining_cents
        ctx.require(
            amount <= open_item.remaining_cents,
            f"amount {fmt(amount)} exceeds remaining {fmt(open_item.remaining_cents)}",
            remaining_cents=open_item.remaining_cents,
        )
        posting_date = payload.posting_date or _today()
        supplier = ctx.get(Supplier, invoice.supplier_id, "Supplier")
        payment = SupplierPayment(
            number=ctx.number_for("SupplierPayment"),
            supplier_id=supplier.id,
            invoice_id=invoice.id,
            amount_cents=amount,
            posting_date=posting_date.isoformat(),
        )
        p = Projection()
        p.create("SupplierPayment", payment, primary=True)
        p.journal = JournalSpec(
            posting_date,
            f"Payment {payment.number} for {invoice.number}",
            "SupplierPayment",
            payment.id,
            [
                LineSpec(ACCT_AP, debit_cents=amount, description=f"settle {invoice.number}"),
                LineSpec(ACCT_CASH, credit_cents=amount, description=f"paid {supplier.code}"),
            ],
        )
        payment.journal_entry_id = p.journal.id
        remaining = open_item.remaining_cents - amount
        p.open_items.append(
            DocumentEffect(
                "OpenItem",
                "update",
                open_item,
                {
                    "remaining_cents": remaining,
                    "status": "paid" if remaining == 0 else "partially_paid",
                },
            )
        )
        if remaining == 0:
            p.update("SupplierInvoice", invoice, {"status": "paid"})
        p.facts = {
            "payment": {"amount_cents": amount, "remaining_after_cents": remaining},
            **ctx.period_facts(posting_date),
        }
        p.extra = {"remaining_after": fmt(remaining)}
        p.events.append(
            EventSpec(
                "supplier_payment.recorded",
                f"{payment.number}: paid {fmt(amount)} on {invoice.number}; remaining {fmt(remaining)}",
            )
        )
        p.compensation = Compensation("reverse_supplier_payment", {"payment": payment.number})
        return p


# ======================================================================================
# cancel_purchase_order
# ======================================================================================
class CancelPOPayload(_Strict):
    po: str
    reason: str = Field(min_length=1, description="Why the PO is cancelled")


@tool
class CancelPurchaseOrder(WriteTool):
    name = "cancel_purchase_order"
    module = "procurement"
    scope = "procurement:write"
    purpose = "Cancel a purchase order that has not been received or invoiced."
    preconditions = [
        "PO status is draft or approved",
        "no posted goods receipts (reverse them first)",
    ]
    effects = "PO -> cancelled; pending approval requests -> expired; GL: none; events: purchase_order.cancelled."
    compensating_tool = None
    common_errors = ["PRECONDITION_FAILED listing the blocking documents"]
    emits = ["purchase_order.cancelled"]
    payload_model = CancelPOPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: CancelPOPayload) -> Projection:
        po = ctx.get_by_ref(PurchaseOrder, payload.po, "PurchaseOrder")
        grns = [g for g in ctx.find(GoodsReceipt, po_id=po.id) if g.status == "posted"]
        invoices = [i for i in ctx.find(SupplierInvoice, po_id=po.id) if i.status != "reversed"]
        blockers = [g.number for g in grns] + [i.number for i in invoices]
        p = Projection()
        p.extra = {"blocking_documents": blockers}
        ctx.require(
            po.status in ("draft", "approved", "partially_received") and not blockers,
            f"PO {po.number} is {po.status} with downstream documents {blockers}; reverse them first"
            if blockers
            else f"PO {po.number} is {po.status} and cannot be cancelled",
            status=po.status,
            blocking_documents=blockers,
        )
        p.update(
            "PurchaseOrder",
            po,
            {"status": "cancelled", "cancelled_reason": payload.reason},
            primary=True,
        )
        for req in ctx.find(ApprovalRequest, document_id=po.id, status="pending"):
            ctx.touch(req)
            p.update(
                "ApprovalRequest",
                req,
                {"status": "expired", "decided_at": ctx.now, "decision_comment": "PO cancelled"},
            )
        p.facts = {"po": _po_facts(po, [])}
        p.events.append(
            EventSpec("purchase_order.cancelled", f"PO {po.number} cancelled: {payload.reason}")
        )
        return p


# ======================================================================================
# reverse_goods_receipt
# ======================================================================================
class ReverseGRNPayload(_Strict):
    grn: str = Field(description="GRN number or id")
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class ReverseGoodsReceipt(WriteTool):
    name = "reverse_goods_receipt"
    module = "procurement"
    scope = "procurement:write"
    purpose = "Reverse a goods receipt: books a mirror journal entry and takes the stock back out."
    preconditions = [
        "GRN is posted (not already reversed)",
        "received qty not yet invoiced",
        "stock still on hand for stocked items",
        "period open",
    ]
    effects = "Reversing GoodsReceipt (negative lines) + reversing JE (Dr/Cr swapped); inventory: on_hand -= qty; PO lines received_qty reduced and PO status recomputed; original GRN -> reversed; events: goods.receipt_reversed."
    compensating_tool = None
    common_errors = ["PRECONDITION_FAILED when invoiced or stock already consumed", "PERIOD_CLOSED"]
    emits = ["goods.receipt_reversed"]
    payload_model = ReverseGRNPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReverseGRNPayload) -> Projection:
        from anerp.core.projection import InventoryDelta
        from anerp.finance.models import JournalEntry
        from anerp.ledger.posting import reversal_spec

        grn = ctx.get_by_ref(GoodsReceipt, payload.grn, "GoodsReceipt")
        ctx.require(grn.status == "posted", f"GRN {grn.number} is {grn.status}", status=grn.status)
        po = ctx.get(PurchaseOrder, grn.po_id, "PurchaseOrder")
        lines = _po_lines(ctx, po)
        by_id = {line.id: line for line in lines}
        posting_date = payload.posting_date or _today()
        p = Projection()
        received_after: dict[str, int] = {}
        for gl in grn.lines:
            line = by_id[gl["po_line_id"]]
            qty = int(gl["qty"])
            ctx.require(
                line.received_qty - qty >= line.invoiced_qty,
                f"{line.sku}: {line.invoiced_qty} already invoiced; reverse the invoice first",
                sku=line.sku,
            )
            item = ctx.get(Item, line.item_id, "Item")
            if item.is_stocked:
                ctx.require(
                    item.on_hand_qty >= qty,
                    f"{item.sku}: only {item.on_hand_qty} on hand, cannot reverse {qty}",
                    sku=item.sku,
                    on_hand=item.on_hand_qty,
                )
                p.inventory.append(InventoryDelta(item, item.sku, -qty))
            received_after[line.id] = line.received_qty - qty
            p.update("PurchaseOrderLine", line, {"received_qty": line.received_qty - qty})
        rev = GoodsReceipt(
            number=ctx.number_for("GoodsReceipt"),
            po_id=po.id,
            received_at=ctx.now,
            lines=[{**gl, "qty": -int(gl["qty"])} for gl in grn.lines],
            total_cents=-grn.total_cents,
            reversal_of_id=grn.id,
        )
        p.create("GoodsReceipt", rev, primary=True)
        p.update("GoodsReceipt", grn, {"status": "reversed"})
        original_je = ctx.get(JournalEntry, grn.journal_entry_id or "", "JournalEntry")
        p.journal = reversal_spec(
            ctx.session,
            original_je,
            posting_date,
            f"Reversal of {grn.number}: {payload.reason}",
            "GoodsReceipt",
            rev.id,
        )
        rev.journal_entry_id = p.journal.id
        p.update("JournalEntry", original_je, {"status": "reversed"})
        new_status = _po_status_after(lines, received_after, {})
        if po.status in ("partially_received", "received"):
            p.update("PurchaseOrder", po, {"status": new_status})
        p.facts = {"po": _po_facts(po, lines), **ctx.period_facts(posting_date)}
        p.events.append(
            EventSpec(
                "goods.receipt_reversed",
                f"GRN {grn.number} reversed by {rev.number}: {payload.reason}",
            )
        )
        return p


# ======================================================================================
# reverse_supplier_invoice
# ======================================================================================
class ReverseSINVPayload(_Strict):
    invoice: str
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class ReverseSupplierInvoice(WriteTool):
    name = "reverse_supplier_invoice"
    module = "procurement"
    scope = "finance:ap:write"
    purpose = "Reverse an unpaid supplier invoice, reopening the GR/IR balance and closing the AP open item."
    preconditions = [
        "invoice status posted (unpaid, no partial payments) or blocked",
        "period open",
    ]
    effects = "Reversing JE (Dr/Cr swapped); AP OpenItem -> reversed; invoice -> reversed; PO lines invoiced_qty reduced; events: supplier_invoice.reversed."
    compensating_tool = None
    common_errors = [
        "PRECONDITION_FAILED when partially or fully paid (reverse the payment first)",
        "PERIOD_CLOSED",
    ]
    emits = ["supplier_invoice.reversed"]
    payload_model = ReverseSINVPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReverseSINVPayload) -> Projection:
        from anerp.finance.models import JournalEntry
        from anerp.ledger.posting import reversal_spec

        invoice = ctx.get_by_ref(SupplierInvoice, payload.invoice, "SupplierInvoice")
        ctx.require(
            invoice.status in ("posted", "blocked"),
            f"invoice {invoice.number} is {invoice.status}",
            status=invoice.status,
        )
        posting_date = payload.posting_date or _today()
        po = ctx.get(PurchaseOrder, invoice.po_id, "PurchaseOrder")
        lines = _po_lines(ctx, po)
        p = Projection()
        p.update("SupplierInvoice", invoice, {"status": "reversed"}, primary=True)
        if invoice.status == "posted":
            open_item = ctx.get(OpenItem, invoice.open_item_id or "", "OpenItem")
            ctx.require(
                open_item.remaining_cents == open_item.amount_cents,
                f"invoice {invoice.number} has payments; reverse them first",
                remaining_cents=open_item.remaining_cents,
            )
            p.open_items.append(
                DocumentEffect(
                    "OpenItem", "update", open_item, {"status": "reversed", "remaining_cents": 0}
                )
            )
            original_je = ctx.get(JournalEntry, invoice.journal_entry_id or "", "JournalEntry")
            p.journal = reversal_spec(
                ctx.session,
                original_je,
                posting_date,
                f"Reversal of {invoice.number}: {payload.reason}",
                "SupplierInvoice",
                invoice.id,
            )
            p.update("JournalEntry", original_je, {"status": "reversed"})
            by_id = {line.id: line for line in lines}
            invoiced_after: dict[str, int] = {}
            for il in invoice.lines:
                line = by_id[il["po_line_id"]]
                invoiced_after[line.id] = line.invoiced_qty - int(il["invoice_qty"])
                p.update(
                    "PurchaseOrderLine",
                    line,
                    {"invoiced_qty": line.invoiced_qty - int(il["invoice_qty"])},
                )
            new_status = _po_status_after(lines, {}, invoiced_after)
            if new_status != po.status and po.status == "invoiced":
                p.update("PurchaseOrder", po, {"status": new_status})
        p.facts = {"po": _po_facts(po, lines), **ctx.period_facts(posting_date)}
        p.events.append(
            EventSpec(
                "supplier_invoice.reversed", f"SINV {invoice.number} reversed: {payload.reason}"
            )
        )
        return p


# ======================================================================================
# reverse_supplier_payment
# ======================================================================================
class ReversePaymentPayload(_Strict):
    payment: str
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class ReverseSupplierPayment(WriteTool):
    name = "reverse_supplier_payment"
    module = "procurement"
    scope = "finance:ap:pay"
    purpose = "Reverse a supplier payment (e.g. bounced or duplicate), restoring the AP open item."
    preconditions = ["payment is posted", "period open"]
    effects = "Reversing JE (Dr 1000 Cash / Cr 2000 AP); AP OpenItem remaining += amount; invoice -> posted; payment -> reversed; events: supplier_payment.reversed."
    compensating_tool = None
    common_errors = ["PERIOD_CLOSED", "PRECONDITION_FAILED if already reversed"]
    emits = ["supplier_payment.reversed"]
    payload_model = ReversePaymentPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReversePaymentPayload) -> Projection:
        from anerp.finance.models import JournalEntry
        from anerp.ledger.posting import reversal_spec

        payment = ctx.get_by_ref(SupplierPayment, payload.payment, "SupplierPayment")
        ctx.require(
            payment.status == "posted",
            f"payment {payment.number} is {payment.status}",
            status=payment.status,
        )
        posting_date = payload.posting_date or _today()
        invoice = ctx.get(SupplierInvoice, payment.invoice_id, "SupplierInvoice")
        open_item = ctx.get(OpenItem, invoice.open_item_id or "", "OpenItem")
        p = Projection()
        p.update("SupplierPayment", payment, {"status": "reversed"}, primary=True)
        remaining = open_item.remaining_cents + payment.amount_cents
        p.open_items.append(
            DocumentEffect(
                "OpenItem",
                "update",
                open_item,
                {
                    "remaining_cents": remaining,
                    "status": "open" if remaining == open_item.amount_cents else "partially_paid",
                },
            )
        )
        if invoice.status == "paid":
            p.update("SupplierInvoice", invoice, {"status": "posted"})
        original_je = ctx.get(JournalEntry, payment.journal_entry_id or "", "JournalEntry")
        p.journal = reversal_spec(
            ctx.session,
            original_je,
            posting_date,
            f"Reversal of {payment.number}: {payload.reason}",
            "SupplierPayment",
            payment.id,
        )
        p.update("JournalEntry", original_je, {"status": "reversed"})
        p.facts = {
            "payment": {"amount_cents": payment.amount_cents},
            **ctx.period_facts(posting_date),
        }
        p.events.append(
            EventSpec(
                "supplier_payment.reversed",
                f"{payment.number} reversed: {payload.reason}; {invoice.number} remaining {fmt(remaining)}",
            )
        )
        return p
