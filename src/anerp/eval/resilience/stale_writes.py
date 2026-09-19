"""Experiment 2 - concurrency / stale writes (deterministic, scripted contention).

Actor A prepares a write from what it saw, actor B changes the world underneath it, A writes.
On the treatment surface A simulates, B commits, A commits against its simulation_id (and, as a
second trial, without one - an agent that skipped simulate). On the control surface A reads
rows, B mutates rows, A writes rows from its stale read; the resulting posting is then checked
for correctness by hand, because the CRUD surface has nothing that would refuse it.

Scenarios: stock consumed, period closed, PO already invoiced, credit limit consumed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from anerp.eval.crud_server import crud_call

SCENARIOS = ("stock_consumed", "period_closed", "po_already_invoiced", "credit_limit_consumed")


def _env(tool: str, mode: str, payload: dict[str, Any], actor: str, **extra: Any) -> dict[str, Any]:
    from anerp.core.dispatch import dispatch
    from anerp.core.envelope import Actor, Envelope, local_principal

    return dispatch(
        Envelope(
            tool=tool,
            mode=mode,
            idempotency_key=extra.pop("key", None)
            or (f"{actor}-{uuid.uuid4().hex}" if mode == "commit" else None),
            actor=Actor(id=actor, kind="agent"),
            payload=payload,
            **extra,
        ),
        principal=local_principal(actor),
    )


def _code(r: dict[str, Any]) -> str:
    if r.get("ok"):
        return str(r.get("status") or ("simulated" if r.get("mode") == "simulate" else "ok"))
    return str(r["error"]["code"])


def _q(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    from anerp.core.dispatch import run_query
    from anerp.core.envelope import Actor, local_principal

    r = run_query(
        name,
        payload,
        Actor(id="eval:resilience", kind="admin"),
        principal=local_principal("eval:resilience"),
    )
    return dict(r["result"])


def _fresh(database_url: str | None) -> None:
    from anerp import db
    from anerp.core.requestlog import request_log, simulations
    from anerp.ledger.receipts import keyring
    from anerp.seed import seed_fixture

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
        _env(
            "reset_and_seed",
            "commit",
            {"fixture_name": "baseline", "confirm": "RESET"},
            "eval:resilience",
        )


# ----------------------------------------------------------------------------- treatment
def treatment(scenario: str) -> dict[str, Any]:
    """A simulates; B commits a conflicting change; A commits with its simulation_id, then A
    re-simulates; in a second fresh setup A commits without any simulation."""
    A, B = "agent:A", "agent:B"
    interfere: Callable[[], dict[str, Any]]
    if scenario == "stock_consumed":  # VALVE-2IN: 5 on hand; A wants 5, B takes 3 first
        so_a = _env(
            "create_sales_order",
            "commit",
            {"customer": "NORTH", "lines": [{"sku": "VALVE-2IN", "qty": 5}]},
            A,
        )["document"]["number"]
        so_b = _env(
            "create_sales_order",
            "commit",
            {"customer": "NORTH", "lines": [{"sku": "VALVE-2IN", "qty": 3}]},
            B,
        )["document"]["number"]
        tool, payload = "ship_order", {"so": so_a}

        def interfere() -> dict[str, Any]:
            return _env("ship_order", "commit", {"so": so_b}, B)

    elif scenario == "period_closed":  # A posts into last month; B closes it first
        from anerp.eval.tasks_loader import placeholders

        prev = placeholders()["previous_period"]
        tool = "post_journal_entry"
        payload = {
            "memo": "late accrual",
            "posting_date": f"{prev}-15",
            "lines": [
                {"account": "5100", "debit": "100.00"},
                {"account": "2000", "credit": "100.00"},
            ],
        }

        def interfere() -> dict[str, Any]:
            return _env("close_period", "commit", {"period": prev}, B)

    elif scenario == "po_already_invoiced":  # 4 received; both invoice all 4
        po = _env(
            "create_purchase_order",
            "commit",
            {"supplier": "BOLT", "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}]},
            A,
        )["document"]["number"]
        _env(
            "receive_goods", "commit", {"po": po}, "eval:resilience"
        )  # admin-kind actor would park; use a human
        tool = "post_supplier_invoice"
        payload = {
            "po": po,
            "supplier_reference": "BOLT-A",
            "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}],
        }

        def interfere() -> dict[str, Any]:
            return _env(
                "post_supplier_invoice",
                "commit",
                {
                    "po": po,
                    "supplier_reference": "BOLT-B",
                    "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}],
                },
                B,
            )

    elif (
        scenario == "credit_limit_consumed"
    ):  # HARB limit 5,000: A wants 4,000; B invoices 1,600 first
        tool, payload = (
            "create_sales_order",
            {"customer": "HARB", "lines": [{"sku": "VALVE-2IN", "qty": 50}]},
        )  # 50 x 80.00

        def interfere() -> (
            dict[str, Any]
        ):  # B sells and invoices 40 x HOSE-10M @ 40.00 = 1,600; with A's 4,000 that is 5,600 > 5,000
            so_b = _env(
                "create_sales_order",
                "commit",
                {"customer": "HARB", "lines": [{"sku": "HOSE-10M", "qty": 40}]},
                B,
            )["document"]["number"]  # 40 x 40.00 = 1,600
            _env("ship_order", "commit", {"so": so_b}, B)
            return _env("issue_customer_invoice", "commit", {"so": so_b}, B)
    else:
        raise ValueError(scenario)

    sim = _env(tool, "simulate", payload, A)
    touched_before = (
        {
            r["id"]: r.get("state_version")
            for r in (sim.get("touched") or sim.get("effects", {}).get("touched") or [])
        }
        if sim.get("ok")
        else {}
    )
    interfered = interfere()
    if not interfered.get("ok"):
        raise RuntimeError(f"{scenario}: B's interference did not apply: {interfered.get('error')}")
    commit_with_sim = (
        _env(tool, "commit", payload, A, simulation_id=sim.get("simulation_id"))
        if sim.get("ok")
        else {"ok": False, "error": {"code": "SIMULATE_FAILED"}}
    )
    resim = _env(tool, "simulate", payload, A)
    resim_code = (
        _code(resim)
        if not resim.get("ok")
        else str(resim.get("commit_would_fail_with") or "would_commit")
    )
    return {
        "arm": "treatment",
        "scenario": scenario,
        "tool": tool,
        "simulate": _code(sim),
        "interference": _code(interfered),
        "commit_with_simulation": _code(commit_with_sim),
        "commit_with_simulation_message": (commit_with_sim.get("error") or {}).get("message", "")[
            :160
        ],
        "resimulate": resim_code,
        "touched_rows_in_simulation": len(touched_before),
        "tb_balanced": _q("get_trial_balance", {})["is_balanced"],
    }


def treatment_without_simulation(scenario: str) -> dict[str, Any]:
    """The same contention when A never simulated (commit straight away after B's change)."""
    A, B = "agent:A", "agent:B"
    if scenario == "stock_consumed":
        so_a = _env(
            "create_sales_order",
            "commit",
            {"customer": "NORTH", "lines": [{"sku": "VALVE-2IN", "qty": 5}]},
            A,
        )["document"]["number"]
        so_b = _env(
            "create_sales_order",
            "commit",
            {"customer": "NORTH", "lines": [{"sku": "VALVE-2IN", "qty": 3}]},
            B,
        )["document"]["number"]
        _env("ship_order", "commit", {"so": so_b}, B)
        r = _env("ship_order", "commit", {"so": so_a}, A)
    elif scenario == "period_closed":
        from anerp.eval.tasks_loader import placeholders

        prev = placeholders()["previous_period"]
        _env("close_period", "commit", {"period": prev}, B)
        r = _env(
            "post_journal_entry",
            "commit",
            {
                "memo": "late accrual",
                "posting_date": f"{prev}-15",
                "lines": [
                    {"account": "5100", "debit": "100.00"},
                    {"account": "2000", "credit": "100.00"},
                ],
            },
            A,
        )
    elif scenario == "po_already_invoiced":
        po = _env(
            "create_purchase_order",
            "commit",
            {"supplier": "BOLT", "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}]},
            A,
        )["document"]["number"]
        _env("receive_goods", "commit", {"po": po}, "eval:resilience")
        _env(
            "post_supplier_invoice",
            "commit",
            {
                "po": po,
                "supplier_reference": "BOLT-B",
                "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}],
            },
            B,
        )
        r = _env(
            "post_supplier_invoice",
            "commit",
            {
                "po": po,
                "supplier_reference": "BOLT-A",
                "lines": [{"sku": "HOSE-10M", "qty": 4, "unit_cost": "25.00"}],
            },
            A,
        )
    elif scenario == "credit_limit_consumed":
        so_b = _env(
            "create_sales_order",
            "commit",
            {"customer": "HARB", "lines": [{"sku": "HOSE-10M", "qty": 40}]},
            B,
        )["document"]["number"]
        _env("ship_order", "commit", {"so": so_b}, B)
        _env("issue_customer_invoice", "commit", {"so": so_b}, B)
        r = _env(
            "create_sales_order",
            "commit",
            {"customer": "HARB", "lines": [{"sku": "VALVE-2IN", "qty": 50}]},
            A,
        )
    else:
        raise ValueError(scenario)
    return {
        "commit_without_simulation": _code(r),
        "tb_balanced": _q("get_trial_balance", {})["is_balanced"],
    }


# ----------------------------------------------------------------------------- control
def _rows(table: str, **filters: Any) -> list[dict[str, Any]]:
    return list(
        crud_call("list_rows", {"table": table, "filters": filters, "limit": 500})["result"]
    )


def _ins(table: str, **values: Any) -> str:
    r = crud_call("insert_row", {"table": table, "values": values})
    if not r.get("ok"):
        raise RuntimeError(f"insert into {table} failed: {r['error']['message']}")
    return str(r["result"]["id"])


def _upd(table: str, id_: str, **values: Any) -> None:
    crud_call("update_row", {"table": table, "id": id_, "values": values})


def control(scenario: str) -> dict[str, Any]:
    """A reads, B mutates the same rows, A writes from its stale read. Nothing refuses it; the
    question is whether the books are right afterwards."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    today = now[:10]
    acct = {r["code"]: r["id"] for r in _rows("account")}
    period = _rows("fiscal_period", code=today[:7])[0]

    def je(
        memo: str, lines: list[tuple[str, int, int]], period_row: dict[str, Any], date: str
    ) -> str:
        n = max((int(j["number"].split("-")[-1]) for j in _rows("journal_entry")), default=0) + 1
        je_id = _ins(
            "journal_entry",
            number=f"JE-{n:06d}",
            period_id=period_row["id"],
            period_code=period_row["code"],
            posting_date=date,
            memo=memo,
            source_type="ManualJournal",
            source_id="",
            status="posted",
            total_debit_cents=sum(d for _, d, _ in lines),
        )
        for i, (code, d, c) in enumerate(lines, start=1):
            _ins(
                "journal_line",
                entry_id=je_id,
                line_no=i,
                account_id=acct[code],
                account_code=code,
                debit_cents=d,
                credit_cents=c,
                description=memo,
            )
        return je_id

    if scenario == "stock_consumed":
        item = _rows("item", sku="VALVE-2IN")[0]  # A reads: 5 on hand
        seen = item["on_hand_qty"]
        # B ships 3: updates the row A already read
        _upd("item", item["id"], on_hand_qty=seen - 3)
        _ins(
            "shipment",
            number="SHP-000001",
            so_id=_ins(
                "sales_order",
                number="SO-000001",
                customer_id=_rows("customer", code="NORTH")[0]["id"],
                status="shipped",
                total_cents=24000,
                created_by="agent:B",
            ),
            shipped_at=now,
            lines=[{"sku": "VALVE-2IN", "qty": 3}],
            cogs_cents=15000,
            status="posted",
        )
        je("ship B", [("5000", 15000, 0), ("1300", 0, 15000)], period, today)
        # A ships 5 from its stale read
        _upd("item", item["id"], on_hand_qty=seen - 5)
        _ins(
            "shipment",
            number="SHP-000002",
            so_id=_ins(
                "sales_order",
                number="SO-000002",
                customer_id=_rows("customer", code="NORTH")[0]["id"],
                status="shipped",
                total_cents=40000,
                created_by="agent:A",
            ),
            shipped_at=now,
            lines=[{"sku": "VALVE-2IN", "qty": 5}],
            cogs_cents=25000,
            status="posted",
        )
        je("ship A", [("5000", 25000, 0), ("1300", 0, 25000)], period, today)
        shipped = sum(
            int(ln["qty"])
            for s in _rows("shipment")
            for ln in (
                s["lines"] if isinstance(s["lines"], list) else __import__("json").loads(s["lines"])
            )
        )
        on_hand = _rows("item", sku="VALVE-2IN")[0]["on_hand_qty"]
        correct = shipped <= seen and on_hand == seen - shipped
        detail = f"{shipped} units shipped against {seen} on hand; item row shows {on_hand} (true: {seen - shipped})"
    elif scenario == "period_closed":
        from anerp.eval.tasks_loader import placeholders

        prev = placeholders()["previous_period"]
        p = _rows("fiscal_period", code=prev)[0]  # A reads: open
        _upd("fiscal_period", p["id"], status="closed")  # B closes it
        je(
            "late accrual", [("5100", 10000, 0), ("2000", 0, 10000)], p, f"{prev}-15"
        )  # A posts from its stale read
        posted_in_closed = [
            j["number"]
            for j in _rows("journal_entry", period_code=prev)
            if j["memo"] == "late accrual"
        ]
        correct = not posted_in_closed
        detail = f"{len(posted_in_closed)} entry posted into closed period {prev}"
    elif scenario == "po_already_invoiced":
        sup = _rows("supplier", code="BOLT")[0]
        po_id = _ins(
            "purchase_order",
            number="PO-000001",
            supplier_id=sup["id"],
            status="received",
            total_cents=10000,
            created_by="agent:A",
            approved_by="policy:auto",
        )
        line_id = _ins(
            "purchase_order_line",
            po_id=po_id,
            line_no=1,
            item_id=_rows("item", sku="HOSE-10M")[0]["id"],
            sku="HOSE-10M",
            qty=4,
            unit_cost_cents=2500,
            received_qty=4,
            invoiced_qty=0,
        )
        line = _rows("purchase_order_line", po_id=po_id)[0]  # A reads: received 4, invoiced 0
        # B invoices all 4
        _ins(
            "supplier_invoice",
            number="SINV-000001",
            supplier_id=sup["id"],
            po_id=po_id,
            supplier_reference="BOLT-B",
            lines=[{"sku": "HOSE-10M", "invoice_qty": 4}],
            total_cents=10000,
            posting_date=today,
            status="posted",
        )
        _upd("purchase_order_line", line_id, invoiced_qty=4)
        je("invoice B", [("1400", 10000, 0), ("2000", 0, 10000)], period, today)
        # A invoices all 4 from its stale read (invoiced 0 -> 4)
        _ins(
            "supplier_invoice",
            number="SINV-000002",
            supplier_id=sup["id"],
            po_id=po_id,
            supplier_reference="BOLT-A",
            lines=[{"sku": "HOSE-10M", "invoice_qty": 4}],
            total_cents=10000,
            posting_date=today,
            status="posted",
        )
        _upd("purchase_order_line", line_id, invoiced_qty=line["invoiced_qty"] + 4)
        je("invoice A", [("1400", 10000, 0), ("2000", 0, 10000)], period, today)
        billed = sum(4 for _ in _rows("supplier_invoice", po_id=po_id))
        inv_qty = _rows("purchase_order_line", po_id=po_id)[0]["invoiced_qty"]
        correct = billed <= 4
        detail = f"{billed} units invoiced against 4 received; PO line shows invoiced_qty {inv_qty}; GR/IR 1400 net {_q('get_account_balance', {'account_code': '1400'})['net_cents']} cents"
    elif scenario == "credit_limit_consumed":
        cust = _rows("customer", code="HARB")[0]
        exposure_seen = sum(
            o["remaining_cents"] for o in _rows("open_item", kind="ar", party_id=cust["id"])
        )  # A reads: 0
        # B invoices 1,600
        so_b = _ins(
            "sales_order",
            number="SO-000001",
            customer_id=cust["id"],
            status="invoiced",
            total_cents=160000,
            created_by="agent:B",
        )
        inv_b = _ins(
            "customer_invoice",
            number="CINV-000001",
            customer_id=cust["id"],
            so_id=so_b,
            lines=[],
            total_cents=160000,
            posting_date=today,
            due_date=today,
            status="posted",
        )
        _ins(
            "open_item",
            kind="ar",
            party_id=cust["id"],
            source_doc_type="CustomerInvoice",
            source_doc_id=inv_b,
            source_doc_number="CINV-000001",
            amount_cents=160000,
            remaining_cents=160000,
            due_date=today,
            status="open",
        )
        je("invoice B", [("1200", 160000, 0), ("4000", 0, 160000)], period, today)
        # A creates a 4,000 order because headroom looked like 5,000 - 0
        if exposure_seen + 400000 <= cust["credit_limit_cents"]:
            _ins(
                "sales_order",
                number="SO-000002",
                customer_id=cust["id"],
                status="open",
                total_cents=400000,
                created_by="agent:A",
            )
        exposure_now = sum(
            o["remaining_cents"] for o in _rows("open_item", kind="ar", party_id=cust["id"])
        )
        orders = sum(
            o["total_cents"] for o in _rows("sales_order", customer_id=cust["id"], status="open")
        )
        correct = exposure_now + orders <= cust["credit_limit_cents"]
        detail = f"open AR {exposure_now} + open orders {orders} = {exposure_now + orders} cents against limit {cust['credit_limit_cents']}"
    else:
        raise ValueError(scenario)
    from anerp.eval.metrics import unsafe_writes_control

    return {
        "arm": "control",
        "scenario": scenario,
        "posting_correct": correct,
        "detail": detail,
        "post_hoc_checker_flags": unsafe_writes_control(_q),
        "tb_balanced": _q("get_trial_balance", {})["is_balanced"],
    }


def run(database_url: str | None = None) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        _fresh(database_url)
        t = treatment(scenario)
        _fresh(database_url)
        t.update(treatment_without_simulation(scenario))
        trials.append(t)
        _fresh(database_url)
        trials.append(control(scenario))
    lines = [
        "| scenario | treatment: commit with simulation | re-simulate says | commit without simulation | control: posting correct? | control detail | post-hoc checker |",
        "|---|---|---|---|---|---|---|",
    ]
    for scenario in SCENARIOS:
        t = next(x for x in trials if x["arm"] == "treatment" and x["scenario"] == scenario)
        c = next(x for x in trials if x["arm"] == "control" and x["scenario"] == scenario)
        lines.append(
            f"| {scenario} | {t['commit_with_simulation']} | {t['resimulate']} | {t['commit_without_simulation']} | {'yes' if c['posting_correct'] else 'NO'} | {c['detail']} | {'; '.join(c['post_hoc_checker_flags']) or 'nothing flagged'} |"
        )
    return {"experiment": "stale_writes", "trials": trials, "summary_md": "\n".join(lines)}
