"""Experiment 3 - commit failure / event-state divergence (deterministic, no agents).

A failure is injected at every distinct stage of `core.dispatch._commit`'s transaction, for
several write tools, and after each the kernel must show all-or-nothing: no document, journal
entry or line, open item, receipt, event or idempotency record from the failed commit; the
trial balance balanced; a retry of the same envelope (same idempotency key) applied cleanly
(not a false replay of a request that never landed); and a second retry replayed.

Stages (after policy evaluation, in commit order):
  documents          after documents, open items and inventory deltas were flushed
  journal            after the journal entry and its lines were posted
  events             after the first event was emitted
  receipt            after the receipt was signed and flushed
  idempotency        after the idempotency record was stored
  db_commit          the database refused the COMMIT itself (OperationalError)
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

STAGES = ("documents", "journal", "events", "receipt", "idempotency", "db_commit")


class InjectedFailure(RuntimeError):
    """Raised by the injector after the stage's real work was done."""


def _count(session: Session, model: Any) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one()[0])  # type: ignore[call-overload]


def snapshot(session: Session) -> dict[str, int]:
    from anerp.approvals.models import ApprovalRequest
    from anerp.events.models import Event
    from anerp.finance.models import JournalEntry, JournalLine, OpenItem
    from anerp.ledger.models import IdempotencyRecord, Receipt
    from anerp.models import DOCUMENT_TYPES

    counts = {
        t: _count(session, m)
        for t, m in DOCUMENT_TYPES.items()
        if t not in ("Account", "Supplier", "Customer", "Item", "FiscalPeriod")
    }
    counts.update(
        {
            "JournalEntry": _count(session, JournalEntry),
            "JournalLine": _count(session, JournalLine),
            "OpenItem": _count(session, OpenItem),
            "Receipt": _count(session, Receipt),
            "Event": _count(session, Event),
            "IdempotencyRecord": _count(session, IdempotencyRecord),
            "ApprovalRequest": _count(session, ApprovalRequest),
        }
    )
    return counts


@contextlib.contextmanager
def inject(stage: str) -> Iterator[dict[str, bool]]:
    """Patch the commit path so the given stage completes and then fails. Yields a state dict
    whose `fired` flag says whether the stage was reached (a tool without a journal never
    reaches the journal stage)."""
    from anerp.core import dispatch as d

    saved: list[tuple[Any, str, Any]] = []
    state = {"fired": False}

    def patch(obj: Any, name: str, fn: Any) -> None:
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, fn)

    def after(orig: Callable[..., Any], flush: bool = False) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            orig(*args, **kwargs)
            if flush:
                session = next((a for a in args if isinstance(a, Session)), None)
                if session is not None:
                    session.flush()
            state["fired"] = True
            raise InjectedFailure(stage)

        return wrapper

    if stage == "documents":  # documents/open items/inventory are added before post_journal

        def fail_before_journal(session: Session, spec: Any) -> Any:
            session.flush()
            state["fired"] = True
            raise InjectedFailure(stage)

        patch(d, "post_journal", fail_before_journal)
        # tools without a journal never reach post_journal: fail at the first emit instead
        patch(d, "emit", after(d.emit, flush=True))
    elif stage == "journal":
        patch(d, "post_journal", after(d.post_journal, flush=True))
    elif stage == "events":
        patch(d, "emit", after(d.emit, flush=True))
    elif stage == "receipt":

        def fail_after_receipt(session: Session, *a: Any, **k: Any) -> Any:
            session.flush()  # the receipt is added and flushed just before this call
            state["fired"] = True
            raise InjectedFailure(stage)

        patch(d.idempotency, "store", fail_after_receipt)
    elif stage == "idempotency":
        patch(d.idempotency, "store", after(d.idempotency.store, flush=True))
    elif stage == "db_commit":

        def failing_commit(self: Session) -> None:
            self.flush()
            state["fired"] = True
            raise OperationalError("COMMIT", {}, Exception("injected: connection lost at COMMIT"))

        patch(Session, "commit", failing_commit)
    else:
        raise ValueError(f"unknown stage {stage}")
    try:
        yield state
    finally:
        for obj, name, orig in reversed(saved):
            setattr(obj, name, orig)


def _dispatch(tool: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
    from anerp.core.dispatch import dispatch
    from anerp.core.envelope import Actor, Envelope, local_principal

    return dispatch(
        Envelope(
            tool=tool,
            mode="commit",
            idempotency_key=key,
            actor=Actor(id="eval:resilience", kind="human"),
            payload=payload,
        ),
        principal=local_principal("eval:resilience"),
    )


CASES: list[tuple[str, dict[str, Any], list[str]]] = [
    # (tool, payload, setup tools that must have run first) - each exercises different effects
    (
        "post_journal_entry",
        {
            "memo": "resilience",
            "lines": [
                {"account": "5100", "debit": "10.00"},
                {"account": "1000", "credit": "10.00"},
            ],
        },
        [],
    ),
    (
        "create_purchase_order",
        {"supplier": "ACME", "lines": [{"sku": "VALVE-2IN", "qty": 2, "unit_cost": "50.00"}]},
        [],
    ),
    ("ship_order", {"so": "$so"}, ["so"]),
    (
        "post_supplier_invoice",
        {
            "po": "$po",
            "supplier_reference": "RES-1",
            "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}],
        },
        ["po_received"],
    ),
]


def _setup(name: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    if name == "so":
        r = _dispatch(
            "create_sales_order",
            {"customer": "NORTH", "lines": [{"sku": "VALVE-2IN", "qty": 2}]},
            f"res-setup-{uuid.uuid4().hex}",
        )
        refs["so"] = r["document"]["number"]
    if name == "po_received":
        r = _dispatch(
            "create_purchase_order",
            {"supplier": "BOLT", "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}]},
            f"res-setup-{uuid.uuid4().hex}",
        )
        refs["po"] = r["document"]["number"]
        _dispatch("receive_goods", {"po": refs["po"]}, f"res-setup-{uuid.uuid4().hex}")
    return refs


def _resolve(payload: dict[str, Any], refs: dict[str, str]) -> dict[str, Any]:
    return {
        k: (refs[v[1:]] if isinstance(v, str) and v.startswith("$") else v)
        for k, v in payload.items()
    }


def run(database_url: str | None = None) -> dict[str, Any]:
    """Every case x stage on a fresh baseline; returns per-trial rows and a summary."""
    from anerp import db
    from anerp.core.dispatch import run_query
    from anerp.core.envelope import Actor, local_principal
    from anerp.core.requestlog import request_log, simulations
    from anerp.ledger.receipts import keyring
    from anerp.seed import seed_fixture

    def fresh() -> None:
        if not database_url or database_url == "sqlite://":
            engine = db.make_engine("sqlite://")
            db.set_engine(engine)
            db.init_db(engine)
            keyring.reset()
            request_log.clear()
            simulations.clear()
            with db.session_scope() as s:
                seed_fixture(s, "baseline")
        else:
            engine = db.make_engine(database_url)
            db.set_engine(engine)
            db.init_db(engine)
            _dispatch(
                "reset_and_seed",
                {"fixture_name": "baseline", "confirm": "RESET"},
                f"res-reset-{uuid.uuid4().hex}",
            )

    def tb_balanced() -> bool:
        r = run_query(
            "get_trial_balance",
            {},
            Actor(id="eval:resilience", kind="admin"),
            principal=local_principal("eval:resilience"),
        )
        return bool(r["result"]["is_balanced"])

    backend = (
        "sqlite"
        if not database_url or database_url == "sqlite://"
        else "postgres " + database_url.split("@")[-1]
    )
    backend = (
        "sqlite"
        if not database_url or database_url == "sqlite://"
        else "postgres " + database_url.split("@")[-1]
    )
    trials: list[dict[str, Any]] = []
    for tool, payload, setup in CASES:
        for stage in STAGES:
            fresh()
            refs: dict[str, str] = {}
            for s_ in setup:
                refs.update(_setup(s_))
            resolved = _resolve(payload, refs)
            key = f"res-{tool}-{stage}-{uuid.uuid4().hex[:8]}"
            with db.session_scope() as s:
                before = snapshot(s)
            # The dispatcher turns the injected exception into an INTERNAL error envelope; the
            # transaction must have rolled back and the response must say so.
            with inject(stage) as state:
                out = _dispatch(tool, resolved, key)
            if not state["fired"]:
                trials.append(
                    {"tool": tool, "stage": stage, "backend": backend, "applicable": False}
                )
                continue
            error_code = (out.get("error") or {}).get("code") if not out.get("ok") else None
            with db.session_scope() as s:
                after = snapshot(s)
            leaked = {k: after[k] - before[k] for k in before if after[k] != before[k]}
            balanced = tb_balanced()
            retry = _dispatch(tool, resolved, key)
            retry_status = (
                retry.get("status") if retry.get("ok") else retry.get("error", {}).get("code")
            )
            replay = _dispatch(tool, resolved, key)
            replay_status = (
                replay.get("status") if replay.get("ok") else replay.get("error", {}).get("code")
            )
            trials.append(
                {
                    "tool": tool,
                    "stage": stage,
                    "backend": backend,
                    "applicable": True,
                    "response": (
                        "error envelope " + str(error_code)
                        if error_code
                        else "ok " + str(out.get("status"))
                    ),
                    "leaked_rows": leaked,
                    "all_or_nothing": not leaked and not out.get("ok"),
                    "tb_balanced_after": balanced,
                    "retry_same_key": retry_status,
                    "second_retry": replay_status,
                }
            )
    ok = all(
        t["all_or_nothing"]
        and t["tb_balanced_after"]
        and t["retry_same_key"] == "applied"
        and t["second_retry"] == "replayed"
        for t in trials
        if t["applicable"]
    )
    return {
        "experiment": "commit_failure",
        "stages": list(STAGES),
        "trials": trials,
        "all_pass": ok,
    }
