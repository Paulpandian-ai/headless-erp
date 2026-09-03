"""Fiscal period helpers and the close-readiness checklist."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from sqlmodel import Session, select

from anerp.approvals.models import ApprovalRequest
from anerp.finance.models import FiscalPeriod
from anerp.ledger.trial_balance import trial_balance
from anerp.procurement.models import PurchaseOrder, PurchaseOrderLine, SupplierInvoice
from anerp.sales.models import SalesOrderLine


def period_bounds(code: str) -> tuple[date, date]:
    year, month = (int(x) for x in code.split("-"))
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def ensure_periods(session: Session, year: int) -> list[FiscalPeriod]:
    created = []
    for month in range(1, 13):
        code = f"{year:04d}-{month:02d}"
        if session.exec(select(FiscalPeriod).where(FiscalPeriod.code == code)).first() is None:
            start, end = period_bounds(code)
            p = FiscalPeriod(code=code, start_date=start, end_date=end)
            session.add(p)
            created.append(p)
    session.flush()
    return created


def close_readiness(session: Session, period: FiscalPeriod) -> dict[str, Any]:
    blocked = session.exec(
        select(SupplierInvoice).where(
            SupplierInvoice.status == "blocked",
            SupplierInvoice.posting_date >= period.start_date.isoformat(),
            SupplierInvoice.posting_date <= period.end_date.isoformat(),
        )
    ).all()
    tb = trial_balance(session, period.code)
    draft_pos = session.exec(select(PurchaseOrder).where(PurchaseOrder.status == "draft")).all()
    pending_approvals = session.exec(
        select(ApprovalRequest).where(ApprovalRequest.status == "pending")
    ).all()
    uninvoiced_receipts = session.exec(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.received_qty > PurchaseOrderLine.invoiced_qty
        )  # type: ignore[arg-type]
    ).all()
    uninvoiced_shipments = session.exec(
        select(SalesOrderLine).where(SalesOrderLine.shipped_qty > SalesOrderLine.invoiced_qty)  # type: ignore[arg-type]
    ).all()
    grir_open = sum(
        (line.received_qty - line.invoiced_qty) * line.unit_cost_cents
        for line in uninvoiced_receipts
    )
    blockers = []
    if blocked:
        blockers.append(
            f"{len(blocked)} blocked supplier invoice(s): {[i.number for i in blocked]}"
        )
    if not tb["is_balanced"]:
        blockers.append("trial balance does not balance")
    warnings = []
    if draft_pos:
        warnings.append(f"{len(draft_pos)} purchase order(s) still draft/awaiting approval")
    if pending_approvals:
        warnings.append(f"{len(pending_approvals)} pending approval request(s)")
    if uninvoiced_receipts:
        warnings.append(
            f"open GR/IR balance {grir_open} cents on {len(uninvoiced_receipts)} PO line(s)"
        )
    if uninvoiced_shipments:
        warnings.append(f"{len(uninvoiced_shipments)} shipped SO line(s) not yet invoiced")
    return {
        "period": period.code,
        "status": period.status,
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "blocked_supplier_invoices": [i.number for i in blocked],
        "trial_balance_ok": tb["is_balanced"],
        "trial_balance_totals": {
            "debit_cents": tb["total_debit_cents"],
            "credit_cents": tb["total_credit_cents"],
        },
        "draft_purchase_orders": [po.number for po in draft_pos],
        "pending_approvals": len(pending_approvals),
        "open_gr_ir_cents": grir_open,
        "uninvoiced_shipment_lines": len(uninvoiced_shipments),
    }
