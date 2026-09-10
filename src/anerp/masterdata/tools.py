"""Master data tools (DESIGN.md §7.1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from anerp.core.context import ToolContext
from anerp.core.errors import precondition
from anerp.core.money import Money, cents
from anerp.core.projection import Compensation, EventSpec, Projection
from anerp.core.registry import Annotations, WriteTool, tool
from anerp.masterdata.models import ACCOUNT_TYPES, Account, Customer, Item, Supplier


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _unique(ctx: ToolContext, model: Any, attr: str, value: str) -> None:
    existing = ctx.session.exec(select(model).where(getattr(model, attr) == value)).first()
    if existing is not None:
        raise precondition(
            f"{model.__name__} with {attr} '{value}' already exists",
            **{attr: value, "existing_id": existing.id},
        )


class CreateSupplierPayload(_Strict):
    code: str = Field(
        min_length=1, max_length=32, description="Short unique supplier code, e.g. ACME"
    )
    name: str = Field(min_length=1, description="Legal or trading name")
    payment_terms_days: int = Field(
        default=30, ge=0, le=365, description="Days from invoice to due date"
    )


@tool
class CreateSupplier(WriteTool):
    name = "create_supplier"
    module = "masterdata"
    scope = "masterdata:write"
    purpose = "Register a supplier you can raise purchase orders against."
    preconditions = ["supplier code must be unique"]
    effects = (
        "Supplier record created (active); GL: none; inventory: none; events: supplier.created."
    )
    compensating_tool = "deactivate_supplier"
    compensating_when = "after creation, blocks new purchase orders"
    common_errors = ["PRECONDITION_FAILED when the code already exists"]
    emits = ["supplier.created"]
    payload_model = CreateSupplierPayload

    def project(self, ctx: ToolContext, payload: CreateSupplierPayload) -> Projection:
        _unique(ctx, Supplier, "code", payload.code)
        supplier = Supplier(
            code=payload.code, name=payload.name, payment_terms_days=payload.payment_terms_days
        )
        p = Projection()
        p.create("Supplier", supplier, primary=True)
        p.events.append(
            EventSpec("supplier.created", f"Supplier {supplier.code} ({supplier.name}) created")
        )
        p.compensation = Compensation("deactivate_supplier", {"supplier": supplier.code})
        p.extra = {"uniqueness": {"code": payload.code, "available": True}}
        return p


class CreateCustomerPayload(_Strict):
    code: str = Field(
        min_length=1, max_length=32, description="Short unique customer code, e.g. NORTH"
    )
    name: str = Field(min_length=1)
    credit_limit: Money = Field(
        default=0, description="Maximum open receivables allowed, e.g. 25000.00"
    )
    payment_terms_days: int = Field(default=30, ge=0, le=365)


@tool
class CreateCustomer(WriteTool):
    name = "create_customer"
    module = "masterdata"
    scope = "masterdata:write"
    purpose = "Register a customer with a credit limit so sales orders can be raised for them."
    preconditions = ["customer code must be unique"]
    effects = "Customer record created (active); GL: none; events: customer.created."
    compensating_tool = "deactivate_customer"
    compensating_when = "after creation, blocks new sales orders"
    emits = ["customer.created"]
    payload_model = CreateCustomerPayload

    def project(self, ctx: ToolContext, payload: CreateCustomerPayload) -> Projection:
        _unique(ctx, Customer, "code", payload.code)
        customer = Customer(
            code=payload.code,
            name=payload.name,
            credit_limit_cents=cents(payload.credit_limit),
            payment_terms_days=payload.payment_terms_days,
        )
        p = Projection()
        p.create("Customer", customer, primary=True)
        p.events.append(
            EventSpec("customer.created", f"Customer {customer.code} ({customer.name}) created")
        )
        p.compensation = Compensation("deactivate_customer", {"customer": customer.code})
        return p


class CreateItemPayload(_Strict):
    sku: str = Field(
        min_length=1, max_length=64, description="Unique stock keeping unit, e.g. VALVE-2IN"
    )
    name: str = Field(min_length=1)
    standard_cost: Money = Field(
        default=0, description="Standard cost per unit used for inventory and COGS"
    )
    list_price: Money = Field(default=0, description="Default selling price per unit")
    is_stocked: bool = Field(
        default=True,
        description="Stocked items hit inventory (1300); services expense on receipt (5100)",
    )


@tool
class CreateItem(WriteTool):
    name = "create_item"
    module = "masterdata"
    scope = "masterdata:write"
    purpose = "Create a purchasable/sellable item with a standard cost and list price."
    preconditions = ["sku must be unique"]
    effects = "Item record created with on_hand_qty 0; GL: none; events: item.created."
    compensating_tool = "deactivate_item"
    compensating_when = "after creation, blocks new order lines"
    emits = ["item.created"]
    payload_model = CreateItemPayload

    def project(self, ctx: ToolContext, payload: CreateItemPayload) -> Projection:
        _unique(ctx, Item, "sku", payload.sku)
        item = Item(
            sku=payload.sku,
            name=payload.name,
            standard_cost_cents=cents(payload.standard_cost),
            list_price_cents=cents(payload.list_price),
            is_stocked=payload.is_stocked,
        )
        p = Projection()
        p.create("Item", item, primary=True)
        p.events.append(EventSpec("item.created", f"Item {item.sku} ({item.name}) created"))
        p.compensation = Compensation("deactivate_item", {"item": item.sku})
        return p


class CreateAccountPayload(_Strict):
    code: str = Field(min_length=1, max_length=16, description="Numeric-style GL code, e.g. 5300")
    name: str = Field(min_length=1)
    type: Literal["asset", "liability", "equity", "revenue", "expense"]


@tool
class CreateAccount(WriteTool):
    name = "create_account"
    module = "masterdata"
    scope = "masterdata:write"
    purpose = "Add an account to the chart of accounts."
    preconditions = ["account code must be unique", f"type in {ACCOUNT_TYPES}"]
    effects = "Account created (active); GL: none; events: account.created."
    compensating_tool = "deactivate_account"
    compensating_when = "when the account has no need to receive further postings"
    emits = ["account.created"]
    payload_model = CreateAccountPayload

    def project(self, ctx: ToolContext, payload: CreateAccountPayload) -> Projection:
        _unique(ctx, Account, "code", payload.code)
        acct = Account(code=payload.code, name=payload.name, type=payload.type)
        p = Projection()
        p.create("Account", acct, primary=True)
        p.events.append(EventSpec("account.created", f"Account {acct.code} {acct.name} created"))
        p.compensation = Compensation("deactivate_account", {"account": acct.code})
        return p


class RefPayload(_Strict):
    ref: str = Field(description="Code / SKU / account code or id of the master record")
    reason: str = Field(default="", description="Why the record is being (de)activated")


def _toggle(kind: str, model: Any, ref_field: str, active: bool) -> type[WriteTool]:
    verb = "activate" if active else "deactivate"
    event = f"{kind}.{'activated' if active else 'deactivated'}"

    class _Toggle(WriteTool):
        name = f"{verb}_{kind}"
        module = "masterdata"
        scope = "masterdata:write"
        purpose = (
            f"{'Reactivate' if active else 'Deactivate'} a {kind}; "
            f"{'allows' if active else 'blocks'} its use on new documents. Nothing is deleted."
        )
        preconditions = [
            f"{kind} exists",
            f"{kind} is currently {'inactive' if active else 'active'}",
        ]
        effects = f"{kind} is_active set to {active}; GL: none; events: {event}."
        compensating_tool = f"{'deactivate' if active else 'activate'}_{kind}"
        compensating_when = "any time"
        emits = [event]
        payload_model = RefPayload
        annotations = Annotations(destructive=not active)

        def project(self, ctx: ToolContext, payload: RefPayload) -> Projection:
            row = ctx.get_by_ref(model, payload.ref, kind.capitalize())
            ctx.require(
                row.is_active != active,
                f"{kind} {payload.ref} is already {'active' if active else 'inactive'}",
            )
            p = Projection()
            p.update(model.__name__, row, {"is_active": active}, primary=True)
            p.events.append(
                EventSpec(
                    event,
                    f"{kind} {getattr(row, ref_field)} {verb}d: {payload.reason or 'no reason given'}",
                )
            )
            p.compensation = Compensation(
                f"{'deactivate' if active else 'activate'}_{kind}", {"ref": payload.ref}
            )
            return p

    _Toggle.__name__ = f"{verb.capitalize()}{kind.capitalize()}"
    return _Toggle


for _kind, _model, _field in (
    ("supplier", Supplier, "code"),
    ("customer", Customer, "code"),
    ("item", Item, "sku"),
    ("account", Account, "code"),
):
    tool(_toggle(_kind, _model, _field, False))
    tool(_toggle(_kind, _model, _field, True))
