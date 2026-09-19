"""Hypothesis: the dispatcher's invariants hold for arbitrary payloads across every write tool.

For random sequences of (tool, payload) - payloads generated from each tool's Pydantic model,
with document references resolved against the live kernel so that many commits land and the
rest fail validation, policy or preconditions - after every step:

  simulate never writes      row counts of every table and the event sequence are unchanged
  commit is all-or-nothing   ok -> the document, receipt, balanced journal and idempotency record
                             exist; not ok -> row counts and the event sequence are unchanged
  replay never creates       the same key + payload again -> `replayed`, same document, no writes
  the trial balance balances after every step
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, get_args, get_origin

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlmodel import SQLModel

from anerp import db
from anerp.core.dispatch import dispatch, run_query
from anerp.core.envelope import Actor, Envelope
from anerp.core.registry import registry
from anerp.core.requestlog import request_log, simulations
from anerp.events.models import Event
from anerp.finance.models import JournalLine
from anerp.ledger.receipts import keyring
from anerp.policy import engine as policy_engine
from anerp.seed import CHART_OF_ACCOUNTS, CUSTOMERS, ITEMS, SUPPLIERS, seed_fixture

PARKED_TABLES = {"approval_request", "receipt", "event", "idempotency_record", "__event_seq"}
ADMIN_ONLY = {"mint_token", "revoke_token", "update_policy", "rotate_signing_key", "reset_and_seed"}
HUMAN = Actor(id="human:prop", kind="human")  # humans may approve and accept goods

registry.ensure_loaded()
WRITE_TOOLS = sorted(t.name for t in registry.write_tools() if t.name not in ADMIN_ONLY)

# References an agent could plausibly use; "$<Type>" is resolved at run time against the kernel
# to the newest document of that type, or left as a random string when none exists yet.
REF_FIELDS = {
    "po": "$PurchaseOrder",
    "so": "$SalesOrder",
    "grn": "$GoodsReceipt",
    "invoice": "$Invoice",  # supplier or customer, chosen per tool
    "payment": "$Payment",
    "shipment": "$Shipment",
    "je": "$JournalEntry",
    "request_id": "$ApprovalRequest",
    "document_id": "$PurchaseOrder",
}
CODES = [c for c, _, _ in CHART_OF_ACCOUNTS]
SKUS = [i[0] for i in ITEMS]
SUPPLIER_CODES = [s[0] for s in SUPPLIERS]
CUSTOMER_CODES = [c[0] for c in CUSTOMERS]

money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999.99"), places=2).map(str)
qty = st.integers(min_value=1, max_value=60)
short_text = st.text(alphabet="abcdefghijklmnopqrstuvwxyz -", min_size=1, max_size=12)
maybe_date = st.one_of(
    st.none(), st.dates(min_value=date.today() - timedelta(days=70), max_value=date.today())
)


def _field_strategy(name: str, annotation: Any, tool: str) -> st.SearchStrategy[Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is not None and type(None) in args:  # Optional[X]
        inner = next(a for a in args if a is not type(None))
        return st.one_of(st.none(), _field_strategy(name, inner, tool))
    if name in ("supplier",):
        return st.sampled_from(SUPPLIER_CODES + ["NOPE"])
    if name in ("customer",):
        return st.sampled_from(CUSTOMER_CODES + ["NOPE"])
    if name == "sku":
        return st.sampled_from(SKUS + ["NOSKU"])
    if name == "account":
        return st.sampled_from(CODES + ["9999"])
    if name in ("period",):
        return st.sampled_from(["{previous}", "{current}", "{closed}", "1999-01"])
    if name == "ref":
        return st.sampled_from(SUPPLIER_CODES + CUSTOMER_CODES + SKUS + CODES + ["NOPE"])
    if name == "code":
        return st.text(alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ", min_size=3, max_size=5)
    if name in REF_FIELDS:
        return st.just(REF_FIELDS[name])
    if name in (
        "amount",
        "unit_cost",
        "unit_price",
        "debit",
        "credit",
        "credit_limit",
        "standard_cost",
        "list_price",
    ):
        return money
    if name in ("qty", "opening_qty", "damaged_qty"):
        return qty if name != "damaged_qty" else st.integers(min_value=0, max_value=3)
    if name in ("payment_terms_days",):
        return st.integers(min_value=0, max_value=90)
    if origin is list:
        item = args[0]
        if isinstance(item, type) and issubclass(item, BaseModel):
            return st.lists(_model_strategy(item, tool), min_size=1, max_size=3)
        return st.lists(short_text, min_size=0, max_size=2)
    if origin is not None and str(origin).endswith("Literal"):
        return st.sampled_from(list(args))
    if get_origin(annotation) is None and isinstance(annotation, type):
        if issubclass(annotation, bool):
            return st.booleans()
        if issubclass(annotation, int):
            return st.integers(min_value=0, max_value=100)
        if issubclass(annotation, Decimal):
            return money
        if issubclass(annotation, date):
            return maybe_date
        if issubclass(annotation, str):
            return short_text
        if issubclass(annotation, BaseModel):
            return _model_strategy(annotation, tool)
    literal_args = get_args(annotation)
    if literal_args and all(isinstance(a, str) for a in literal_args):
        return st.sampled_from(list(literal_args))
    return short_text


def _model_strategy(model: type[BaseModel], tool: str) -> st.SearchStrategy[dict[str, Any]]:
    fields = {}
    for name, f in model.model_fields.items():
        strat = _field_strategy(name, f.annotation, tool)
        fields[name] = strat if f.is_required() else st.one_of(st.none(), strat)
    return st.fixed_dictionaries(fields).map(
        lambda d: {k: v for k, v in d.items() if v is not None}
    )


def _payload_strategy(tool: str) -> st.SearchStrategy[dict[str, Any]]:
    return _model_strategy(registry.get(tool).payload_model, tool)


actions = st.lists(
    st.sampled_from(WRITE_TOOLS).flatmap(lambda t: st.tuples(st.just(t), _payload_strategy(t))),
    min_size=1,
    max_size=8,
)


# ----------------------------------------------------------------------------- kernel access
def _commit(tool: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
    return dispatch(
        Envelope(tool=tool, mode="commit", idempotency_key=key, actor=HUMAN, payload=payload)
    )


def _fresh() -> None:
    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    db.init_db(engine)
    keyring.reset()
    policy_engine.set_engine(None)
    request_log.clear()
    simulations.clear()
    with db.session_scope() as s:
        seed_fixture(s, "baseline")
    # A world with something in it, so generated references resolve and commits can land:
    # one procure-to-pay chain up to the invoice, one order-to-cash chain up to the invoice,
    # and one manual journal. Each step is itself subject to the invariants below only through
    # the random sequence; here they just have to succeed.
    po = _commit(
        "create_purchase_order",
        {"supplier": "BOLT", "lines": [{"sku": "HOSE-10M", "qty": 8, "unit_cost": "25.00"}]},
        f"pro-{uuid.uuid4().hex}",
    )["document"]["number"]
    _commit("receive_goods", {"po": po}, f"pro-{uuid.uuid4().hex}")
    _commit(
        "post_supplier_invoice",
        {
            "po": po,
            "supplier_reference": "PROP-1",
            "lines": [{"sku": "HOSE-10M", "qty": 8, "unit_cost": "25.00"}],
        },
        f"pro-{uuid.uuid4().hex}",
    )
    so = _commit(
        "create_sales_order",
        {"customer": "NORTH", "lines": [{"sku": "FLANGE-4", "qty": 10}]},
        f"pro-{uuid.uuid4().hex}",
    )["document"]["number"]
    _commit("ship_order", {"so": so}, f"pro-{uuid.uuid4().hex}")
    _commit("issue_customer_invoice", {"so": so}, f"pro-{uuid.uuid4().hex}")
    _commit(
        "post_journal_entry",
        {
            "memo": "prologue",
            "lines": [
                {"account": "5100", "debit": "10.00"},
                {"account": "2000", "credit": "10.00"},
            ],
        },
        f"pro-{uuid.uuid4().hex}",
    )


def _counts() -> dict[str, int]:
    with db.session_scope() as s:
        out = {
            name: int(s.exec(select(func.count()).select_from(table)).one()[0])  # type: ignore[call-overload]
            for name, table in SQLModel.metadata.tables.items()
        }
        out["__event_seq"] = int(s.exec(select(func.coalesce(func.max(Event.seq), 0))).one()[0])  # type: ignore[call-overload]
        return out


def _q(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = run_query(name, payload, HUMAN)
    assert r["ok"], r
    return dict(r["result"])


def _newest(type_: str) -> str | None:
    items = _q("search_documents", {"type": type_, "limit": 1})["items"]
    return items[0]["number"] if items else None


def _resolve(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Turn "$Type" markers into the newest matching document number (or a random string)."""
    from anerp.eval.tasks_loader import placeholders

    ph = placeholders()
    periods = {
        "{previous}": ph["previous_period"],
        "{current}": ph["current_period"],
        "{closed}": ph["closed_period"],
    }
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, str) and v.startswith("$"):
            type_ = v[1:]
            if type_ == "Invoice":
                type_ = (
                    "SupplierInvoice"
                    if tool.endswith("supplier_invoice") or tool == "pay_supplier"
                    else "CustomerInvoice"
                )
            if type_ == "Payment":
                type_ = "SupplierPayment" if "supplier" in tool else "CustomerPayment"
            if type_ == "ApprovalRequest":
                pending = _q("list_pending_approvals", {})["pending"]
                out[k] = pending[0]["id"] if pending else f"missing-{uuid.uuid4().hex[:6]}"
                continue
            out[k] = _newest(type_) or f"missing-{uuid.uuid4().hex[:6]}"
        elif isinstance(v, str) and v in periods:
            out[k] = periods[v]
        else:
            out[k] = v
    return out


def _simulate(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    return dispatch(Envelope(tool=tool, mode="simulate", actor=HUMAN, payload=payload))


def _journal_balanced(je_id: str) -> bool:
    with db.session_scope() as s:
        d, c = s.exec(
            select(
                func.coalesce(func.sum(JournalLine.debit_cents), 0),
                func.coalesce(func.sum(JournalLine.credit_cents), 0),
            ).where(JournalLine.entry_id == je_id)  # type: ignore[call-overload]
        ).one()
        return int(d) == int(c) and int(d) > 0


# ----------------------------------------------------------------------------- the property
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(actions=actions)
def test_dispatcher_invariants_hold_for_arbitrary_write_sequences(actions) -> None:
    _fresh()
    for tool, raw in actions:
        payload = _resolve(tool, raw)

        # 1. simulate never writes, whatever it answers
        before = _counts()
        sim = _simulate(tool, payload)
        assert _counts() == before, (tool, payload, sim.get("error"))

        # 2. commit is all-or-nothing
        key = f"prop-{uuid.uuid4().hex}"
        before = _counts()
        r = _commit(tool, payload, key)
        after = _counts()
        if r["ok"]:
            assert r["status"] == "applied", r
            assert after["idempotency_record"] == before["idempotency_record"] + 1, (tool, r)
            assert after["receipt"] == before["receipt"] + 1, (tool, r)
            assert after["__event_seq"] >= before["__event_seq"], (tool, r)
            if r.get("journal_entry"):
                assert _journal_balanced(r["journal_entry"]["id"]), (tool, r["journal_entry"])
            doc = r.get("document")
            if doc and doc.get("type") and doc.get("id"):
                assert _q("get_document", {"id_or_number": doc["id"]})["id"] == doc["id"]
        else:
            changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
            if changed:
                # The one sanctioned write on refusal: the request was parked for a human
                # (REQUIRES_APPROVAL, or a park_on_deny code such as MATCH_VARIANCE_EXCEEDED).
                # It is exactly one approval request with its receipt, event and idempotency
                # record - never a business document, journal line, open item or stock change.
                err = r["error"]
                assert (err.get("details") or {}).get("approval_request_id"), (tool, payload, err)
                assert set(changed) <= PARKED_TABLES, (tool, payload, err["code"], changed)
                assert changed["approval_request"][1] == changed["approval_request"][0] + 1
                assert changed["receipt"][1] == changed["receipt"][0] + 1
                assert changed["idempotency_record"][1] == changed["idempotency_record"][0] + 1
            # otherwise nothing at all was written

        # 3. a replayed key never creates anything
        before = _counts()
        again = _commit(tool, payload, key)
        assert _counts() == before, (tool, again)
        if r["ok"]:
            assert again["ok"] and again["status"] == "replayed", (tool, again)
            assert again.get("document") == r.get("document"), (tool, again)
        else:
            assert not again["ok"], (tool, again)  # a failed commit stores nothing new to replay
            parked = (r["error"].get("details") or {}).get("approval_request_id")
            if parked:  # a parked request is idempotent: the replay names the same request
                assert (again["error"].get("details") or {}).get("approval_request_id") == parked

        # 4. the ledger balances after every step
        assert _q("get_trial_balance", {})["is_balanced"], tool
