"""Order-to-cash tools (DESIGN.md §7.3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlmodel import select

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
from anerp.finance.models import JournalEntry, OpenItem
from anerp.ledger.posting import reversal_spec
from anerp.masterdata.models import Customer, Item
from anerp.sales.models import (
    CreditNote,
    CustomerInvoice,
    CustomerPayment,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)

ACCT_CASH = "1000"
ACCT_AR = "1200"
ACCT_INVENTORY = "1300"
ACCT_REVENUE = "4000"
ACCT_COGS = "5000"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _today() -> date:
    return utcnow().date()


def _so_lines(ctx: ToolContext, so: SalesOrder) -> list[SalesOrderLine]:
    lines = ctx.session.exec(
        select(SalesOrderLine).where(SalesOrderLine.so_id == so.id).order_by(SalesOrderLine.line_no)
    ).all()  # type: ignore[arg-type]
    for line in lines:
        ctx.touch(line)
    return list(lines)


def _so_status_after(
    lines: list[SalesOrderLine], shipped: dict[str, int], invoiced: dict[str, int]
) -> str:
    total = sum(line.qty for line in lines)
    total_shipped = sum(shipped.get(line.id, line.shipped_qty) for line in lines)
    total_invoiced = sum(invoiced.get(line.id, line.invoiced_qty) for line in lines)
    if total > 0 and total_invoiced >= total:
        return "invoiced"
    if total > 0 and total_shipped >= total:
        return "shipped"
    if total_shipped > 0:
        return "partially_shipped"
    return "open"


def open_ar_cents(ctx: ToolContext, customer_id: str) -> int:
    stmt = select(func.coalesce(func.sum(OpenItem.remaining_cents), 0)).where(
        OpenItem.kind == "ar",
        OpenItem.party_id == customer_id,
        OpenItem.status.in_(["open", "partially_paid"]),  # type: ignore[attr-defined]
    )
    return int(ctx.session.exec(stmt).one())


def _credit_facts(ctx: ToolContext, customer: Customer, additional_cents: int) -> dict[str, Any]:
    open_ar = open_ar_cents(ctx, customer.id)
    return {
        "customer_code": customer.code,
        "credit_limit_cents": customer.credit_limit_cents,
        "open_ar_cents": open_ar,
        "document_cents": additional_cents,
        "exposure_after_cents": open_ar + additional_cents,
        "headroom_cents": customer.credit_limit_cents - open_ar,
    }


def _so_facts(so: SalesOrder) -> dict[str, Any]:
    return {
        "id": so.id,
        "number": so.number,
        "status": so.status,
        "total_cents": so.total_cents,
        "customer_id": so.customer_id,
        "created_by": so.created_by,
    }


# ======================================================================================
class SOLineInput(_Strict):
    sku: str
    qty: Qty
    unit_price: Money | None = Field(default=None, description="Defaults to the item's list price")


class CreateSOPayload(_Strict):
    customer: str = Field(description="Customer code or id")
    lines: list[SOLineInput] = Field(min_length=1)
    memo: str = ""


@tool
class CreateSalesOrder(WriteTool):
    name = "create_sales_order"
    module = "sales"
    scope = "sales:write"
    purpose = "Create a sales order for a customer; checks credit exposure (open AR + this order) against the credit limit."
    preconditions = ["customer active", "items active", "qty > 0"]
    effects = (
        "SalesOrder created in status open; GL: none; inventory: none; events: sales_order.created."
    )
    compensating_tool = "cancel_sales_order"
    compensating_when = "before anything ships"
    common_errors = [
        "CREDIT_LIMIT_EXCEEDED (reduce qty or record a payment first)",
        "NOT_FOUND",
        "PRECONDITION_FAILED for inactive records",
    ]
    emits = ["sales_order.created"]
    payload_model = CreateSOPayload

    def project(self, ctx: ToolContext, payload: CreateSOPayload) -> Projection:
        customer = ctx.get_by_ref(Customer, payload.customer, "Customer")
        ctx.require_active(customer, "Customer")
        so = SalesOrder(
            number=ctx.number_for("SalesOrder"),
            customer_id=customer.id,
            memo=payload.memo,
            created_by=ctx.actor.id,
        )
        p = Projection()
        p.create("SalesOrder", so, primary=True)
        total = 0
        seen: set[str] = set()
        for i, line in enumerate(payload.lines, start=1):
            item = ctx.get_by_ref(Item, line.sku, "Item")
            ctx.require_active(item, "Item")
            if item.sku in seen:
                raise validation(f"sku {item.sku} appears twice; merge the lines", sku=item.sku)
            seen.add(item.sku)
            price = cents(line.unit_price) if line.unit_price is not None else item.list_price_cents
            total += price * line.qty
            p.create(
                "SalesOrderLine",
                SalesOrderLine(
                    so_id=so.id,
                    line_no=i,
                    item_id=item.id,
                    sku=item.sku,
                    qty=line.qty,
                    unit_price_cents=price,
                ),
            )
        so.total_cents = total
        credit = _credit_facts(ctx, customer, total)
        p.facts = {"so": _so_facts(so), "credit": credit}
        p.extra = {"total": fmt(total), "credit_check": credit}
        p.events.append(
            EventSpec(
                "sales_order.created", f"SO {so.number} for {customer.code} total {fmt(total)}"
            )
        )
        p.compensation = Compensation("cancel_sales_order", {"so": so.number})
        return p


# ======================================================================================
class ShipLineInput(_Strict):
    sku: str
    qty: Qty


class ShipOrderPayload(_Strict):
    so: str = Field(description="SO number or id")
    lines: list[ShipLineInput] | None = Field(
        default=None, description="Omit to ship everything outstanding"
    )
    posting_date: date | None = None


@tool
class ShipOrder(WriteTool):
    name = "ship_order"
    module = "sales"
    scope = "sales:write"
    purpose = "Ship goods against a sales order; relieves inventory and books cost of goods sold at standard cost."
    preconditions = [
        "SO status open or partially_shipped",
        "qty per line <= outstanding",
        "on_hand >= qty for stocked items",
        "period open",
    ]
    effects = "Shipment created; GL: Dr 5000 COGS / Cr 1300 Inventory (qty x standard cost); inventory: on_hand -= qty; SO -> partially_shipped/shipped; events: order.shipped."
    compensating_tool = "reverse_shipment"
    compensating_when = "before the shipment is invoiced"
    common_errors = [
        "INSUFFICIENT_STOCK (receive goods first)",
        "PRECONDITION_FAILED",
        "PERIOD_CLOSED",
    ]
    emits = ["order.shipped"]
    payload_model = ShipOrderPayload

    def project(self, ctx: ToolContext, payload: ShipOrderPayload) -> Projection:
        so = ctx.get_by_ref(SalesOrder, payload.so, "SalesOrder")
        ctx.require(
            so.status in ("open", "partially_shipped"),
            f"SO {so.number} is {so.status}",
            status=so.status,
        )
        posting_date = payload.posting_date or _today()
        lines = _so_lines(ctx, so)
        by_sku = {line.sku: line for line in lines}
        requested = payload.lines or [
            ShipLineInput(sku=line.sku, qty=line.qty - line.shipped_qty)
            for line in lines
            if line.qty > line.shipped_qty
        ]
        ctx.require(bool(requested), f"SO {so.number} has nothing outstanding to ship")
        p = Projection()
        shp = Shipment(number=ctx.number_for("Shipment"), so_id=so.id, shipped_at=ctx.now)
        p.create("Shipment", shp, primary=True)
        cogs = 0
        shp_lines: list[dict[str, Any]] = []
        shipped_after: dict[str, int] = {}
        short: list[dict[str, Any]] = []
        for req in requested:
            line = by_sku.get(req.sku)
            if line is None:
                raise validation(f"sku {req.sku} is not on SO {so.number}", sku=req.sku)
            outstanding = line.qty - line.shipped_qty
            ctx.require(
                req.qty <= outstanding,
                f"cannot ship {req.qty} of {req.sku}: only {outstanding} outstanding",
                sku=req.sku,
                outstanding=outstanding,
            )
            item = ctx.get(Item, line.item_id, "Item")
            line_cogs = 0
            if item.is_stocked:
                if item.on_hand_qty < req.qty:
                    short.append(
                        {
                            "sku": item.sku,
                            "requested": req.qty,
                            "on_hand": item.on_hand_qty,
                            "shortfall": req.qty - item.on_hand_qty,
                        }
                    )
                line_cogs = item.standard_cost_cents * req.qty
                cogs += line_cogs
                p.inventory.append(InventoryDelta(item, item.sku, -req.qty))
            shipped_after[line.id] = line.shipped_qty + req.qty
            p.update("SalesOrderLine", line, {"shipped_qty": line.shipped_qty + req.qty})
            shp_lines.append(
                {
                    "so_line_id": line.id,
                    "sku": item.sku,
                    "qty": req.qty,
                    "unit_price_cents": line.unit_price_cents,
                    "cogs_cents": line_cogs,
                }
            )
        shp.lines = shp_lines
        shp.cogs_cents = cogs
        if cogs > 0:
            p.journal = JournalSpec(
                posting_date,
                f"COGS for shipment {shp.number} (SO {so.number})",
                "Shipment",
                shp.id,
                [
                    LineSpec(ACCT_COGS, debit_cents=cogs, description=f"COGS {shp.number}"),
                    LineSpec(
                        ACCT_INVENTORY,
                        credit_cents=cogs,
                        description=f"inventory relief {shp.number}",
                    ),
                ],
            )
            shp.journal_entry_id = p.journal.id
        new_status = _so_status_after(lines, shipped_after, {})
        p.update("SalesOrder", so, {"status": new_status})
        p.facts = {
            "so": _so_facts(so),
            "stock": {
                "shortfall": bool(short),
                "short_skus": [s["sku"] for s in short],
                "lines": short,
            },
            **ctx.period_facts(posting_date),
        }
        p.extra = {"cogs": fmt(cogs), "stock_check": short or "ok"}
        p.events.append(
            EventSpec(
                "order.shipped",
                f"{shp.number}: shipped against SO {so.number}; COGS {fmt(cogs)}; SO now {new_status}",
            )
        )
        p.compensation = Compensation("reverse_shipment", {"shipment": shp.number})
        return p


# ======================================================================================
class InvoiceLineInput(_Strict):
    sku: str
    qty: Qty


class IssueInvoicePayload(_Strict):
    so: str = Field(description="SO number or id")
    lines: list[InvoiceLineInput] | None = Field(
        default=None, description="Omit to invoice everything shipped but not yet invoiced"
    )
    posting_date: date | None = None


@tool
class IssueCustomerInvoice(WriteTool):
    name = "issue_customer_invoice"
    module = "sales"
    scope = "finance:ar:write"
    purpose = "Invoice shipped quantities on a sales order; books revenue and an AR open item."
    preconditions = [
        "SO has shipments",
        "qty per line <= shipped minus already invoiced",
        "credit exposure within limit",
        "period open",
    ]
    effects = "CustomerInvoice created; GL: Dr 1200 Accounts receivable / Cr 4000 Sales revenue; AR OpenItem created with due date from customer terms; SO -> invoiced when fully invoiced; events: customer_invoice.issued."
    compensating_tool = "issue_credit_note"
    compensating_when = "any time after issue, up to the uncredited amount"
    common_errors = [
        "PRECONDITION_FAILED when nothing shipped",
        "CREDIT_LIMIT_EXCEEDED",
        "PERIOD_CLOSED",
    ]
    emits = ["customer_invoice.issued"]
    payload_model = IssueInvoicePayload

    def project(self, ctx: ToolContext, payload: IssueInvoicePayload) -> Projection:
        so = ctx.get_by_ref(SalesOrder, payload.so, "SalesOrder")
        customer = ctx.get(Customer, so.customer_id, "Customer")
        lines = _so_lines(ctx, so)
        ctx.require(
            any(line.shipped_qty > 0 for line in lines),
            f"SO {so.number} has no shipments yet; ship first",
        )
        posting_date = payload.posting_date or _today()
        by_sku = {line.sku: line for line in lines}
        requested = payload.lines or [
            InvoiceLineInput(sku=line.sku, qty=line.shipped_qty - line.invoiced_qty)
            for line in lines
            if line.shipped_qty > line.invoiced_qty
        ]
        ctx.require(bool(requested), f"SO {so.number} has nothing shipped and uninvoiced")
        p = Projection()
        inv = CustomerInvoice(
            number=ctx.number_for("CustomerInvoice"),
            customer_id=customer.id,
            so_id=so.id,
            posting_date=posting_date.isoformat(),
            due_date=(posting_date + timedelta(days=customer.payment_terms_days)).isoformat(),
        )
        p.create("CustomerInvoice", inv, primary=True)
        total = 0
        inv_lines: list[dict[str, Any]] = []
        invoiced_after: dict[str, int] = {}
        for req in requested:
            line = by_sku.get(req.sku)
            if line is None:
                raise validation(f"sku {req.sku} is not on SO {so.number}", sku=req.sku)
            available = line.shipped_qty - line.invoiced_qty
            ctx.require(
                req.qty <= available,
                f"cannot invoice {req.qty} of {req.sku}: only {available} shipped and uninvoiced",
                sku=req.sku,
                available=available,
            )
            total += line.unit_price_cents * req.qty
            invoiced_after[line.id] = line.invoiced_qty + req.qty
            p.update("SalesOrderLine", line, {"invoiced_qty": line.invoiced_qty + req.qty})
            inv_lines.append(
                {
                    "so_line_id": line.id,
                    "sku": req.sku,
                    "qty": req.qty,
                    "unit_price_cents": line.unit_price_cents,
                    "value_cents": line.unit_price_cents * req.qty,
                }
            )
        inv.lines = inv_lines
        inv.total_cents = total
        inv.shipment_ids = [s.id for s in ctx.find(Shipment, so_id=so.id) if s.status == "posted"]
        p.journal = JournalSpec(
            posting_date,
            f"Customer invoice {inv.number} (SO {so.number})",
            "CustomerInvoice",
            inv.id,
            [
                LineSpec(
                    ACCT_AR, debit_cents=total, description=f"AR {customer.code} {inv.number}"
                ),
                LineSpec(ACCT_REVENUE, credit_cents=total, description=f"revenue {inv.number}"),
            ],
        )
        inv.journal_entry_id = p.journal.id
        open_item = OpenItem(
            kind="ar",
            party_id=customer.id,
            source_doc_type="CustomerInvoice",
            source_doc_id=inv.id,
            source_doc_number=inv.number,
            amount_cents=total,
            remaining_cents=total,
            due_date=posting_date + timedelta(days=customer.payment_terms_days),
        )
        inv.open_item_id = open_item.id
        p.open_items.append(DocumentEffect("OpenItem", "create", open_item))
        new_status = _so_status_after(lines, {}, invoiced_after)
        if new_status != so.status:
            p.update("SalesOrder", so, {"status": new_status})
        credit = _credit_facts(ctx, customer, total)
        p.facts = {
            "so": _so_facts(so),
            "credit": credit,
            "invoice": {"total_cents": total},
            **ctx.period_facts(posting_date),
        }
        p.extra = {"total": fmt(total), "due_date": inv.due_date, "credit_check": credit}
        p.events.append(
            EventSpec(
                "customer_invoice.issued",
                f"{inv.number} issued to {customer.code} for {fmt(total)}, due {inv.due_date}",
            )
        )
        p.compensation = Compensation(
            "issue_credit_note", {"invoice": inv.number, "amount": fmt(total)}
        )
        return p


# ======================================================================================
class RecordPaymentPayload(_Strict):
    invoice: str = Field(description="Customer invoice number (CINV-…) or id")
    amount: PositiveMoney | None = Field(
        default=None, description="Defaults to the remaining balance"
    )
    posting_date: date | None = None


@tool
class RecordCustomerPayment(WriteTool):
    name = "record_customer_payment"
    module = "sales"
    scope = "finance:ar:write"
    purpose = "Record cash received from a customer against an invoice."
    preconditions = ["invoice AR open item remaining > 0", "amount <= remaining", "period open"]
    effects = "CustomerPayment created; GL: Dr 1000 Cash / Cr 1200 Accounts receivable; AR OpenItem remaining -= amount; invoice -> paid when settled; events: customer_payment.recorded."
    compensating_tool = "reverse_customer_payment"
    compensating_when = "while the period is open"
    common_errors = ["PRECONDITION_FAILED when overpaying", "PERIOD_CLOSED"]
    emits = ["customer_payment.recorded"]
    payload_model = RecordPaymentPayload

    def project(self, ctx: ToolContext, payload: RecordPaymentPayload) -> Projection:
        inv = ctx.get_by_ref(CustomerInvoice, payload.invoice, "CustomerInvoice")
        ctx.require(
            inv.status in ("posted",), f"invoice {inv.number} is {inv.status}", status=inv.status
        )
        open_item = ctx.get(OpenItem, inv.open_item_id or "", "OpenItem")
        ctx.require(open_item.remaining_cents > 0, f"invoice {inv.number} has nothing outstanding")
        amount = cents(payload.amount) if payload.amount is not None else open_item.remaining_cents
        ctx.require(
            amount <= open_item.remaining_cents,
            f"amount {fmt(amount)} exceeds remaining {fmt(open_item.remaining_cents)}",
            remaining_cents=open_item.remaining_cents,
        )
        posting_date = payload.posting_date or _today()
        customer = ctx.get(Customer, inv.customer_id, "Customer")
        rcpt = CustomerPayment(
            number=ctx.number_for("CustomerPayment"),
            customer_id=customer.id,
            invoice_id=inv.id,
            amount_cents=amount,
            posting_date=posting_date.isoformat(),
        )
        p = Projection()
        p.create("CustomerPayment", rcpt, primary=True)
        p.journal = JournalSpec(
            posting_date,
            f"Receipt {rcpt.number} for {inv.number}",
            "CustomerPayment",
            rcpt.id,
            [
                LineSpec(
                    ACCT_CASH, debit_cents=amount, description=f"received from {customer.code}"
                ),
                LineSpec(ACCT_AR, credit_cents=amount, description=f"settle {inv.number}"),
            ],
        )
        rcpt.journal_entry_id = p.journal.id
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
            p.update("CustomerInvoice", inv, {"status": "paid"})
        p.facts = {
            "payment": {"amount_cents": amount, "remaining_after_cents": remaining},
            **ctx.period_facts(posting_date),
        }
        p.extra = {"remaining_after": fmt(remaining)}
        p.events.append(
            EventSpec(
                "customer_payment.recorded",
                f"{rcpt.number}: received {fmt(amount)} on {inv.number}; remaining {fmt(remaining)}",
            )
        )
        p.compensation = Compensation("reverse_customer_payment", {"payment": rcpt.number})
        return p


# ======================================================================================
class CreditNotePayload(_Strict):
    invoice: str
    amount: PositiveMoney
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class IssueCreditNote(WriteTool):
    name = "issue_credit_note"
    module = "sales"
    scope = "finance:ar:write"
    purpose = "Issue a credit note against a customer invoice, reducing revenue and the receivable."
    preconditions = [
        "invoice exists",
        "amount <= invoice total minus prior credits",
        "amount <= remaining open balance",
        "period open",
    ]
    effects = "CreditNote created; GL: Dr 4000 Sales revenue / Cr 1200 Accounts receivable; AR OpenItem remaining -= amount; invoice -> credited when fully credited; events: credit_note.issued."
    compensating_tool = None
    common_errors = ["PRECONDITION_FAILED when over-crediting", "PERIOD_CLOSED"]
    emits = ["credit_note.issued"]
    payload_model = CreditNotePayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: CreditNotePayload) -> Projection:
        inv = ctx.get_by_ref(CustomerInvoice, payload.invoice, "CustomerInvoice")
        open_item = ctx.get(OpenItem, inv.open_item_id or "", "OpenItem")
        amount = cents(payload.amount)
        creditable = inv.total_cents - inv.credited_cents
        ctx.require(
            amount <= creditable,
            f"amount {fmt(amount)} exceeds creditable {fmt(creditable)}",
            creditable_cents=creditable,
        )
        ctx.require(
            amount <= open_item.remaining_cents,
            f"amount {fmt(amount)} exceeds open balance {fmt(open_item.remaining_cents)}; refunds are out of scope",
            remaining_cents=open_item.remaining_cents,
        )
        posting_date = payload.posting_date or _today()
        customer = ctx.get(Customer, inv.customer_id, "Customer")
        cn = CreditNote(
            number=ctx.number_for("CreditNote"),
            customer_id=customer.id,
            invoice_id=inv.id,
            amount_cents=amount,
            reason=payload.reason,
            posting_date=posting_date.isoformat(),
        )
        p = Projection()
        p.create("CreditNote", cn, primary=True)
        p.journal = JournalSpec(
            posting_date,
            f"Credit note {cn.number} against {inv.number}: {payload.reason}",
            "CreditNote",
            cn.id,
            [
                LineSpec(ACCT_REVENUE, debit_cents=amount, description=f"credit {inv.number}"),
                LineSpec(ACCT_AR, credit_cents=amount, description=f"reduce AR {customer.code}"),
            ],
        )
        cn.journal_entry_id = p.journal.id
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
        changes: dict[str, Any] = {"credited_cents": inv.credited_cents + amount}
        if inv.credited_cents + amount == inv.total_cents:
            changes["status"] = "credited"
        p.update("CustomerInvoice", inv, changes)
        p.facts = {"credit_note": {"amount_cents": amount}, **ctx.period_facts(posting_date)}
        p.events.append(
            EventSpec(
                "credit_note.issued",
                f"{cn.number}: credited {fmt(amount)} on {inv.number}: {payload.reason}",
            )
        )
        return p


# ======================================================================================
class CancelSOPayload(_Strict):
    so: str
    reason: str = Field(min_length=1)


@tool
class CancelSalesOrder(WriteTool):
    name = "cancel_sales_order"
    module = "sales"
    scope = "sales:write"
    purpose = "Cancel a sales order that has not shipped or been invoiced."
    preconditions = ["SO status open (nothing shipped)"]
    effects = "SO -> cancelled; GL: none; events: sales_order.cancelled."
    compensating_tool = None
    common_errors = ["PRECONDITION_FAILED listing shipments/invoices that block cancellation"]
    emits = ["sales_order.cancelled"]
    payload_model = CancelSOPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: CancelSOPayload) -> Projection:
        so = ctx.get_by_ref(SalesOrder, payload.so, "SalesOrder")
        blockers = [s.number for s in ctx.find(Shipment, so_id=so.id) if s.status == "posted"] + [
            i.number for i in ctx.find(CustomerInvoice, so_id=so.id)
        ]
        p = Projection()
        p.extra = {"blocking_documents": blockers}
        ctx.require(
            so.status == "open" and not blockers,
            f"SO {so.number} is {so.status} with documents {blockers}; reverse shipments first",
            status=so.status,
            blocking_documents=blockers,
        )
        p.update(
            "SalesOrder",
            so,
            {"status": "cancelled", "cancelled_reason": payload.reason},
            primary=True,
        )
        p.facts = {"so": _so_facts(so)}
        p.events.append(
            EventSpec("sales_order.cancelled", f"SO {so.number} cancelled: {payload.reason}")
        )
        return p


# ======================================================================================
class ReverseShipmentPayload(_Strict):
    shipment: str
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class ReverseShipment(WriteTool):
    name = "reverse_shipment"
    module = "sales"
    scope = "sales:write"
    purpose = (
        "Reverse a shipment (goods returned before invoicing): restores stock and reverses COGS."
    )
    preconditions = ["shipment posted", "shipped qty not yet invoiced", "period open"]
    effects = "Reversing JE (Dr 1300 / Cr 5000); inventory: on_hand += qty; SO lines shipped_qty reduced and status recomputed; shipment -> reversed; events: shipment.reversed."
    compensating_tool = None
    common_errors = [
        "PRECONDITION_FAILED when invoiced (issue a credit note instead)",
        "PERIOD_CLOSED",
    ]
    emits = ["shipment.reversed"]
    payload_model = ReverseShipmentPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReverseShipmentPayload) -> Projection:
        shp = ctx.get_by_ref(Shipment, payload.shipment, "Shipment")
        ctx.require(
            shp.status == "posted", f"shipment {shp.number} is {shp.status}", status=shp.status
        )
        so = ctx.get(SalesOrder, shp.so_id, "SalesOrder")
        lines = _so_lines(ctx, so)
        by_id = {line.id: line for line in lines}
        posting_date = payload.posting_date or _today()
        p = Projection()
        shipped_after: dict[str, int] = {}
        for sl in shp.lines:
            line = by_id[sl["so_line_id"]]
            qty = int(sl["qty"])
            ctx.require(
                line.shipped_qty - qty >= line.invoiced_qty,
                f"{line.sku}: {line.invoiced_qty} already invoiced; issue a credit note instead",
                sku=line.sku,
            )
            item = ctx.get(Item, line.item_id, "Item")
            if item.is_stocked:
                p.inventory.append(InventoryDelta(item, item.sku, qty))
            shipped_after[line.id] = line.shipped_qty - qty
            p.update("SalesOrderLine", line, {"shipped_qty": line.shipped_qty - qty})
        p.update("Shipment", shp, {"status": "reversed"}, primary=True)
        if shp.journal_entry_id:
            original_je = ctx.get(JournalEntry, shp.journal_entry_id, "JournalEntry")
            p.journal = reversal_spec(
                ctx.session,
                original_je,
                posting_date,
                f"Reversal of {shp.number}: {payload.reason}",
                "Shipment",
                shp.id,
            )
            p.update("JournalEntry", original_je, {"status": "reversed"})
        new_status = _so_status_after(lines, shipped_after, {})
        p.update("SalesOrder", so, {"status": new_status})
        p.facts = {"so": _so_facts(so), **ctx.period_facts(posting_date)}
        p.events.append(
            EventSpec(
                "shipment.reversed",
                f"{shp.number} reversed: {payload.reason}; SO {so.number} now {new_status}",
            )
        )
        return p


# ======================================================================================
class ReverseCustomerPaymentPayload(_Strict):
    payment: str
    reason: str = Field(min_length=1)
    posting_date: date | None = None


@tool
class ReverseCustomerPayment(WriteTool):
    name = "reverse_customer_payment"
    module = "sales"
    scope = "finance:ar:write"
    purpose = (
        "Reverse a customer payment (bounced cheque, mis-posting), restoring the AR open item."
    )
    preconditions = ["payment posted", "period open"]
    effects = "Reversing JE (Dr 1200 AR / Cr 1000 Cash); AR OpenItem remaining += amount; invoice -> posted; payment -> reversed; events: customer_payment.reversed."
    compensating_tool = None
    common_errors = ["PERIOD_CLOSED", "PRECONDITION_FAILED if already reversed"]
    emits = ["customer_payment.reversed"]
    payload_model = ReverseCustomerPaymentPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: ReverseCustomerPaymentPayload) -> Projection:
        rcpt = ctx.get_by_ref(CustomerPayment, payload.payment, "CustomerPayment")
        ctx.require(
            rcpt.status == "posted", f"payment {rcpt.number} is {rcpt.status}", status=rcpt.status
        )
        posting_date = payload.posting_date or _today()
        inv = ctx.get(CustomerInvoice, rcpt.invoice_id, "CustomerInvoice")
        open_item = ctx.get(OpenItem, inv.open_item_id or "", "OpenItem")
        p = Projection()
        p.update("CustomerPayment", rcpt, {"status": "reversed"}, primary=True)
        remaining = open_item.remaining_cents + rcpt.amount_cents
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
        if inv.status == "paid":
            p.update("CustomerInvoice", inv, {"status": "posted"})
        original_je = ctx.get(JournalEntry, rcpt.journal_entry_id or "", "JournalEntry")
        p.journal = reversal_spec(
            ctx.session,
            original_je,
            posting_date,
            f"Reversal of {rcpt.number}: {payload.reason}",
            "CustomerPayment",
            rcpt.id,
        )
        p.update("JournalEntry", original_je, {"status": "reversed"})
        p.facts = {"payment": {"amount_cents": rcpt.amount_cents}, **ctx.period_facts(posting_date)}
        p.events.append(
            EventSpec(
                "customer_payment.reversed",
                f"{rcpt.number} reversed: {payload.reason}; {inv.number} remaining {fmt(remaining)}",
            )
        )
        return p
