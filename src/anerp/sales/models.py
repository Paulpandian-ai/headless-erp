"""Sales tables (DESIGN.md §5.5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field

from anerp.core.ids import utcnow
from anerp.db import KernelRow

SO_STATUSES = (
    "open",
    "partially_shipped",
    "shipped",
    "invoiced",
    "closed",
    "cancelled",
)


class SalesOrder(KernelRow, table=True):
    __tablename__ = "sales_order"
    number: str = Field(index=True, unique=True, max_length=16)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    status: str = Field(default="open", max_length=20, index=True)
    total_cents: int = 0
    memo: str = ""
    created_by: str = Field(max_length=128)
    cancelled_reason: str | None = None


class SalesOrderLine(KernelRow, table=True):
    __tablename__ = "sales_order_line"
    so_id: str = Field(foreign_key="sales_order.id", index=True)
    line_no: int = 1
    item_id: str = Field(foreign_key="item.id")
    sku: str = Field(max_length=64)
    qty: int
    unit_price_cents: int
    shipped_qty: int = 0
    invoiced_qty: int = 0


class Shipment(KernelRow, table=True):
    __tablename__ = "shipment"
    number: str = Field(index=True, unique=True, max_length=16)
    so_id: str = Field(foreign_key="sales_order.id", index=True)
    shipped_at: datetime = Field(default_factory=utcnow)
    lines: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    journal_entry_id: str | None = Field(default=None, max_length=26)
    cogs_cents: int = 0
    status: str = Field(default="posted", max_length=16)  # posted | reversed
    reversal_of_id: str | None = Field(default=None, max_length=26)
    invoiced_qty_total: int = 0


class CustomerInvoice(KernelRow, table=True):
    __tablename__ = "customer_invoice"
    number: str = Field(index=True, unique=True, max_length=16)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    so_id: str = Field(foreign_key="sales_order.id", index=True)
    shipment_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    lines: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    total_cents: int = 0
    credited_cents: int = 0
    posting_date: str = Field(max_length=10)
    due_date: str = Field(max_length=10)
    journal_entry_id: str | None = Field(default=None, max_length=26)
    open_item_id: str | None = Field(default=None, max_length=26)
    status: str = Field(default="posted", max_length=16)  # posted | paid | credited


class CustomerPayment(KernelRow, table=True):
    __tablename__ = "customer_payment"
    number: str = Field(index=True, unique=True, max_length=16)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    invoice_id: str = Field(foreign_key="customer_invoice.id", index=True)
    amount_cents: int
    posting_date: str = Field(max_length=10)
    journal_entry_id: str | None = Field(default=None, max_length=26)
    status: str = Field(default="posted", max_length=16)  # posted | reversed


class CreditNote(KernelRow, table=True):
    __tablename__ = "credit_note"
    number: str = Field(index=True, unique=True, max_length=16)
    customer_id: str = Field(foreign_key="customer.id", index=True)
    invoice_id: str = Field(foreign_key="customer_invoice.id", index=True)
    amount_cents: int
    reason: str = ""
    posting_date: str = Field(max_length=10)
    journal_entry_id: str | None = Field(default=None, max_length=26)
