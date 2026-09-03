"""Master data tables (DESIGN.md §5.2)."""

from __future__ import annotations

from sqlmodel import Field

from anerp.db import KernelRow

ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")


class Account(KernelRow, table=True):
    __tablename__ = "account"
    code: str = Field(index=True, unique=True, max_length=16)
    name: str
    type: str = Field(max_length=16)
    is_active: bool = True


class Supplier(KernelRow, table=True):
    __tablename__ = "supplier"
    code: str = Field(index=True, unique=True, max_length=32)
    name: str
    payment_terms_days: int = 30
    is_active: bool = True


class Customer(KernelRow, table=True):
    __tablename__ = "customer"
    code: str = Field(index=True, unique=True, max_length=32)
    name: str
    credit_limit_cents: int = 0
    payment_terms_days: int = 30
    is_active: bool = True


class Item(KernelRow, table=True):
    __tablename__ = "item"
    sku: str = Field(index=True, unique=True, max_length=64)
    name: str
    standard_cost_cents: int = 0
    list_price_cents: int = 0
    is_stocked: bool = True
    on_hand_qty: int = 0
    is_active: bool = True
