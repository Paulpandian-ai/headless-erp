"""Document serialization shared by query and troubleshooting tools."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from anerp.approvals.models import ApprovalRequest
from anerp.core.ids import iso
from anerp.events.log import event_to_dict
from anerp.events.models import Event
from anerp.finance.models import JournalEntry, JournalLine, OpenItem
from anerp.ledger.models import Receipt
from anerp.ledger.receipts import receipt_to_dict
from anerp.models import DOCUMENT_TYPES
from anerp.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierInvoice,
    SupplierPayment,
)
from anerp.sales.models import (
    CreditNote,
    CustomerInvoice,
    CustomerPayment,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)

PREFIX_TO_TYPE = {
    "JE": "JournalEntry",
    "PO": "PurchaseOrder",
    "GRN": "GoodsReceipt",
    "SINV": "SupplierInvoice",
    "PAY": "SupplierPayment",
    "SO": "SalesOrder",
    "SHP": "Shipment",
    "CINV": "CustomerInvoice",
    "RCPT": "CustomerPayment",
    "CN": "CreditNote",
}


def base_dump(row: Any) -> dict[str, Any]:
    data = row.model_dump(mode="json")
    data.pop("private_key_pem", None)
    data.pop("token_hash", None)
    return data


def find_document(
    session: Session, ref: str, type_hint: str | None = None
) -> tuple[str, Any] | None:
    """Locate a document by number (prefix decides the type) or by id across all types."""
    if type_hint and type_hint in DOCUMENT_TYPES:
        model = DOCUMENT_TYPES[type_hint]
        row = session.get(model, ref)
        if row is None:
            for attr in ("number", "code", "sku"):
                if hasattr(model, attr):
                    row = session.exec(select(model).where(getattr(model, attr) == ref)).first()
                    if row is not None:
                        break
        return (type_hint, row) if row is not None else None
    prefix = ref.split("-")[0] if "-" in ref else None
    if prefix in PREFIX_TO_TYPE:
        model = DOCUMENT_TYPES[PREFIX_TO_TYPE[prefix]]
        row = session.exec(select(model).where(model.number == ref)).first()  # type: ignore[attr-defined]
        if row is not None:
            return PREFIX_TO_TYPE[prefix], row
    for name, model in DOCUMENT_TYPES.items():
        row = session.get(model, ref)
        if row is not None:
            return name, row
    for name, model in DOCUMENT_TYPES.items():
        for attr in ("code", "sku"):
            if hasattr(model, attr):
                row = session.exec(select(model).where(getattr(model, attr) == ref)).first()
                if row is not None:
                    return name, row
    return None


def journal_lines(session: Session, entry_id: str) -> list[dict[str, Any]]:
    rows = session.exec(
        select(JournalLine).where(JournalLine.entry_id == entry_id).order_by(JournalLine.line_no)
    ).all()  # type: ignore[arg-type]
    return [
        {
            "line_no": line.line_no,
            "account": line.account_code,
            "debit_cents": line.debit_cents,
            "credit_cents": line.credit_cents,
            "description": line.description,
        }
        for line in rows
    ]


def journal_dump(session: Session, je: JournalEntry) -> dict[str, Any]:
    data = base_dump(je)
    data["lines"] = journal_lines(session, je.id)
    reversals = session.exec(select(JournalEntry).where(JournalEntry.reversal_of_id == je.id)).all()
    data["reversed_by"] = [r.number for r in reversals]
    return data


def receipts_for(session: Session, document_id: str) -> list[dict[str, Any]]:
    rows = session.exec(
        select(Receipt).where(Receipt.document_id == document_id).order_by(Receipt.signed_at)
    ).all()  # type: ignore[arg-type]
    return [receipt_to_dict(r) for r in rows]


def events_for(session: Session, document_id: str) -> list[dict[str, Any]]:
    rows = session.exec(
        select(Event).where(Event.document_id == document_id).order_by(Event.seq)
    ).all()  # type: ignore[arg-type]
    return [event_to_dict(e) for e in rows]


def serialize(session: Session, type_name: str, row: Any, *, deep: bool = True) -> dict[str, Any]:
    data = base_dump(row)
    data["type"] = type_name
    if type_name == "PurchaseOrder":
        lines = session.exec(
            select(PurchaseOrderLine)
            .where(PurchaseOrderLine.po_id == row.id)
            .order_by(PurchaseOrderLine.line_no)
        ).all()  # type: ignore[arg-type]
        data["lines"] = [base_dump(line) for line in lines]
        if deep:
            data["goods_receipts"] = [
                base_dump(g)
                for g in session.exec(
                    select(GoodsReceipt).where(GoodsReceipt.po_id == row.id)
                ).all()
            ]
            data["supplier_invoices"] = [
                base_dump(i)
                for i in session.exec(
                    select(SupplierInvoice).where(SupplierInvoice.po_id == row.id)
                ).all()
            ]
            data["approval_requests"] = [
                base_dump(a)
                for a in session.exec(
                    select(ApprovalRequest).where(ApprovalRequest.document_id == row.id)
                ).all()
            ]
    elif type_name == "SalesOrder":
        lines = session.exec(
            select(SalesOrderLine)
            .where(SalesOrderLine.so_id == row.id)
            .order_by(SalesOrderLine.line_no)
        ).all()  # type: ignore[arg-type]
        data["lines"] = [base_dump(line) for line in lines]
        if deep:
            data["shipments"] = [
                base_dump(s)
                for s in session.exec(select(Shipment).where(Shipment.so_id == row.id)).all()
            ]
            data["customer_invoices"] = [
                base_dump(i)
                for i in session.exec(
                    select(CustomerInvoice).where(CustomerInvoice.so_id == row.id)
                ).all()
            ]
    elif type_name == "JournalEntry":
        data = {**data, **journal_dump(session, row)}
    if deep:
        je_id = getattr(row, "journal_entry_id", None)
        if je_id:
            je = session.get(JournalEntry, je_id)
            if je is not None:
                data["journal_entry"] = journal_dump(session, je)
        oi_id = getattr(row, "open_item_id", None)
        if oi_id:
            oi = session.get(OpenItem, oi_id)
            if oi is not None:
                data["open_item"] = base_dump(oi)
        if type_name == "SupplierInvoice":
            data["payments"] = [
                base_dump(p)
                for p in session.exec(
                    select(SupplierPayment).where(SupplierPayment.invoice_id == row.id)
                ).all()
            ]
        if type_name == "CustomerInvoice":
            data["payments"] = [
                base_dump(p)
                for p in session.exec(
                    select(CustomerPayment).where(CustomerPayment.invoice_id == row.id)
                ).all()
            ]
            data["credit_notes"] = [
                base_dump(c)
                for c in session.exec(
                    select(CreditNote).where(CreditNote.invoice_id == row.id)
                ).all()
            ]
        data["receipts"] = receipts_for(session, row.id)
        data["events"] = events_for(session, row.id)
    return data


def summary(type_name: str, row: Any) -> dict[str, Any]:
    return {
        "type": type_name,
        "id": row.id,
        "number": getattr(row, "number", None)
        or getattr(row, "code", None)
        or getattr(row, "sku", None),
        "status": getattr(row, "status", None),
        "total_cents": next(
            (
                getattr(row, a)
                for a in ("total_cents", "total_debit_cents", "amount_cents")
                if hasattr(row, a)
            ),
            None,
        ),
        "created_at": iso(getattr(row, "created_at", None)),
        "state_version": getattr(row, "state_version", None),
    }


__all__ = [
    "PurchaseOrder",
    "SalesOrder",
    "find_document",
    "serialize",
    "summary",
    "journal_dump",
    "receipts_for",
    "events_for",
    "base_dump",
    "PREFIX_TO_TYPE",
]
