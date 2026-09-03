"""Procurement tables (DESIGN.md §5.4)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field

from anerp.core.ids import utcnow
from anerp.db import KernelRow

PO_STATUSES = (
    "draft",
    "approved",
    "partially_received",
    "received",
    "invoiced",
    "closed",
    "cancelled",
)


class PurchaseOrder(KernelRow, table=True):
    __tablename__ = "purchase_order"
    number: str = Field(index=True, unique=True, max_length=16)
    supplier_id: str = Field(foreign_key="supplier.id", index=True)
    status: str = Field(default="draft", max_length=20, index=True)
    total_cents: int = 0
    memo: str = ""
    created_by: str = Field(max_length=128)
    approved_by: str | None = Field(default=None, max_length=128)
    approved_at: datetime | None = None
    cancelled_reason: str | None = None


class PurchaseOrderLine(KernelRow, table=True):
    __tablename__ = "purchase_order_line"
    po_id: str = Field(foreign_key="purchase_order.id", index=True)
    line_no: int = 1
    item_id: str = Field(foreign_key="item.id")
    sku: str = Field(max_length=64)
    qty: int
    unit_cost_cents: int
    received_qty: int = 0
    invoiced_qty: int = 0


class GoodsReceipt(KernelRow, table=True):
    __tablename__ = "goods_receipt"
    number: str = Field(index=True, unique=True, max_length=16)
    po_id: str = Field(foreign_key="purchase_order.id", index=True)
    received_at: datetime = Field(default_factory=utcnow)
    lines: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    journal_entry_id: str | None = Field(default=None, max_length=26)
    total_cents: int = 0
    status: str = Field(default="posted", max_length=16)  # posted | reversed
    reversal_of_id: str | None = Field(default=None, max_length=26)
    invoiced_qty_total: int = 0


class SupplierInvoice(KernelRow, table=True):
    __tablename__ = "supplier_invoice"
    number: str = Field(index=True, unique=True, max_length=16)
    supplier_id: str = Field(foreign_key="supplier.id", index=True)
    po_id: str = Field(foreign_key="purchase_order.id", index=True)
    grn_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    supplier_reference: str = ""
    lines: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    total_cents: int = 0
    variance_cents: int = 0
    match_status: str = Field(default="matched", max_length=32)
    posting_date: str = Field(max_length=10)
    journal_entry_id: str | None = Field(default=None, max_length=26)
    open_item_id: str | None = Field(default=None, max_length=26)
    status: str = Field(default="posted", max_length=16)  # posted | paid | reversed


class SupplierPayment(KernelRow, table=True):
    __tablename__ = "supplier_payment"
    number: str = Field(index=True, unique=True, max_length=16)
    supplier_id: str = Field(foreign_key="supplier.id", index=True)
    invoice_id: str = Field(foreign_key="supplier_invoice.id", index=True)
    amount_cents: int
    posting_date: str = Field(max_length=10)
    journal_entry_id: str | None = Field(default=None, max_length=26)
    status: str = Field(default="posted", max_length=16)  # posted | reversed
