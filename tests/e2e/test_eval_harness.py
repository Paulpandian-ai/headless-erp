"""The eval harness end to end with the deterministic `scripted` client: every task's goal checker
must pass on the treatment server for a correct agent, and the control surface must work."""

from __future__ import annotations

from pathlib import Path

from anerp.eval.clients.base import RunTrace
from anerp.eval.clients.scripted import ScriptedClient
from anerp.eval.crud_server import crud_call, crud_tools
from anerp.eval.metrics import check_goal, duplicate_documents, record_filtered_counts, snapshot
from anerp.eval.report import latency, load_raw, summarize
from anerp.eval.runner import Environment, apply_setup, human_step, run_matrix, run_one
from anerp.eval.tasks_loader import load_tasks


def test_tasks_load() -> None:
    tasks = load_tasks()
    assert len(tasks) == 20
    assert {t["module"] for t in tasks} == {"procurement", "sales", "finance"}
    assert all(t["goal_state"] for t in tasks)


def test_scripted_client_passes_every_task(tmp_path: Path) -> None:
    env = Environment()
    client = ScriptedClient()
    failures = []
    for task in load_tasks():
        row = run_one(env, client, "treatment", task, 1)
        m = row["metrics"]
        if not m["success"]:
            failures.append(
                (task["id"], [g for g in m["goal"] if not g["ok"]], row["trace"]["final_text"])
            )
        assert m["tb_balanced"], task["id"]
        assert m["unsafe_writes"] == 0, task["id"]
        assert m["duplicate_documents"] == 0, (task["id"], m["duplicate_detail"])
        assert m["simulate_before_commit_rate"] in (None, 1.0), task["id"]
    assert not failures, failures


def test_duplicate_documents_counts_only_repeated_requests() -> None:
    """A correct run that creates several different documents scores 0; the same request
    committed again under a fresh idempotency key (a retry storm) scores 1; a replay of the
    same key creates nothing and scores nothing."""
    env = Environment()
    env.reset()
    before = snapshot(env.admin_query)
    po = {"supplier": "ACME", "lines": [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}]}
    env.admin_commit("create_purchase_order", po)
    env.admin_commit(
        "create_purchase_order",
        {"supplier": "ACME", "lines": [{"sku": "VALVE-2IN", "qty": 3, "unit_cost": "50.00"}]},
    )
    env.admin_commit(
        "create_sales_order", {"customer": "NORTH", "lines": [{"sku": "VALVE-2IN", "qty": 5}]}
    )
    env.admin_commit(
        "post_journal_entry",
        {
            "memo": "rent",
            "lines": [{"account": "5100", "debit": "1.00"}, {"account": "2000", "credit": "1.00"}],
        },
    )
    assert duplicate_documents(env.admin_query, before) == []
    second = env.admin_commit("create_purchase_order", po)  # a retry with a new key
    assert duplicate_documents(env.admin_query, before) == [
        f"PurchaseOrder {second['document']['number']}"
    ]


def test_duplicate_documents_tolerates_raw_inserts() -> None:
    """A control agent writes invoice lines in whatever shape it likes; the fingerprint must not
    assume the kernel's keys, and two identical raw inserts must still count as one duplicate."""
    env = Environment()
    env.reset()
    before = snapshot(env.admin_query)
    supplier = crud_call("list_rows", {"table": "supplier", "filters": {"code": "ACME"}})["result"][
        0
    ]
    po = env.admin_commit(
        "create_purchase_order",
        {"supplier": "ACME", "lines": [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}]},
    )["document"]
    for n in (1, 2):
        crud_call(
            "insert_row",
            {
                "table": "supplier_invoice",
                "values": {
                    "number": f"SINV-99999{n}",
                    "supplier_id": supplier["id"],
                    "po_id": po["id"],
                    "supplier_reference": "RAW-1",
                    "lines": [{"item": "VALVE-2IN", "quantity": 10, "price": 50.0}],
                    "total_cents": 50000,
                    "posting_date": "2026-09-11",
                },
            },
        )
    assert duplicate_documents(env.admin_query, before) == ["SupplierInvoice SINV-999992"]


def test_scripted_client_on_control_surface() -> None:
    """The CRUD oracle does its own bookkeeping: every task passes except the one the control
    surface cannot express (no approval requests), and it never leaves the books unbalanced."""
    env = Environment()
    client = ScriptedClient()
    failures = []
    for task in load_tasks():
        row = run_one(env, client, "control", task, 1)
        m = row["metrics"]
        assert m["tb_balanced"], task["id"]
        assert m["unsafe_writes"] == 0, (task["id"], m["unsafe_detail"])
        assert m["duplicate_documents"] == 0, (task["id"], m["duplicate_detail"])
        assert m["tool_calls"] > 0 and row["trace"]["error"] is None, task["id"]
        assert all(c["name"] in CRUD_TOOLS for c in row["trace"]["tool_calls"]), task["id"]
        if not m["success"]:
            failures.append((task["id"], [g["check"] for g in m["goal"] if not g["ok"]]))
    assert failures == [("p2p_04_over_threshold", ["pending_approvals"])]


CRUD_TOOLS = {"list_tables", "list_rows", "get_row", "insert_row", "update_row"}


def test_human_loop_is_the_same_on_both_arms() -> None:
    """The warehouse count reaches the agent on both arms between rounds, with the same numbers
    (the task's acceptance override), and the control agent gets it only once per PO."""
    env = Environment()
    client = ScriptedClient()
    task = next(t for t in load_tasks(["p2p_02_partial_receipt"]))
    rows = {server: run_one(env, client, server, task, 1) for server in ("treatment", "control")}
    for server, row in rows.items():
        assert row["metrics"]["success"], (server, row["metrics"]["goal"])
        assert row["metrics"]["rounds"] == 2, server
    # the control arm's status line names the same count the treatment warehouse accepted
    env.reset()
    apply_setup(env, task)
    env.admin_commit(
        "create_purchase_order",
        {"supplier": "BOLT", "lines": [{"sku": "FLANGE-4", "qty": 200, "unit_cost": "15.00"}]},
    )
    state: dict = {}
    first = human_step(env, task, "control", state)
    assert len(first) == 1 and "FLANGE-4 x80" in first[0] and "no goods receipt" in first[0]
    assert human_step(env, task, "control", state) == []  # reported once


def test_one_of_accepts_either_close_outcome() -> None:
    env = Environment()
    client = ScriptedClient()
    task = next(t for t in load_tasks(["close_01_clean"]))
    closed = run_one(env, client, "treatment", task, 1)
    assert closed["metrics"]["success"] and closed["metrics"]["outcome"] == "closed"
    # an agent that runs the checklist and asks for sign-off instead of closing also passes
    env.reset()
    q = env.admin_query
    before = snapshot(q)
    record_filtered_counts(q, task, before)
    trace = RunTrace(final_text="Checklist is green; please confirm before I close the period.")
    goal = check_goal(q, task, before, trace)
    assert all(g["ok"] for g in goal), goal
    assert goal[0]["actual"] == "asked_for_confirmation"
    trace = RunTrace(final_text="I looked at it.")
    failed = check_goal(q, task, before, trace)[0]
    assert not failed["ok"] and set(failed["actual"]) == {"closed", "asked_for_confirmation"}


def test_seed_calendar_matches_task_placeholders() -> None:
    from anerp.eval.tasks_loader import placeholders

    ph = placeholders()
    env = Environment()
    env.reset()
    assert (
        env.admin_query("get_period", {"period_code": ph["closed_period"]})["period"]["status"]
        == "closed"
    )
    assert (
        env.admin_query("get_period", {"period_code": ph["previous_period"]})["period"]["status"]
        == "open"
    )
    assert (
        env.admin_query("get_period", {"period_code": ph["current_period"]})["period"]["status"]
        == "open"
    )


def test_control_surface_and_matrix_outputs(tmp_path: Path) -> None:
    env = Environment()
    env.reset()
    assert {t["name"] for t in crud_tools()} == {
        "list_tables",
        "list_rows",
        "get_row",
        "insert_row",
        "update_row",
    }
    rows = crud_call("list_rows", {"table": "supplier", "limit": 10})
    assert rows["ok"] and len(rows["result"]) == 2
    ins = crud_call(
        "insert_row",
        {
            "table": "purchase_order",
            "values": {
                "number": "PO-999999",
                "supplier_id": rows["result"][0]["id"],
                "status": "approved",
                "total_cents": 5_000_000,
                "created_by": "crud",
            },
        },
    )
    assert ins["ok"]
    assert crud_call("insert_row", {"table": "nope", "values": {}})["ok"] is False
    result = run_matrix(
        clients=["scripted"],
        servers=["treatment", "control"],
        tasks=["p2p_01_simple", "dup_01_retry_storm"],
        runs=2,
        output_dir=str(tmp_path),
    )
    assert result["runs"] == 8 and result["successes"] == 8
    raw = load_raw(Path(result["raw"]))
    summary = summarize(raw)
    by_arm = {(s["server"], s["task"]): s for s in summary}
    treat = by_arm[("treatment", "p2p_01_simple")]
    assert treat["success_rate"] == 1.0 and treat["simulate_before_commit_rate"] == 1.0
    assert by_arm[("control", "p2p_01_simple")]["avg_tool_calls"] > treat["avg_tool_calls"]
    lat = {(row["server"], row["tool"]): row for row in latency(raw)}
    for server in ("treatment", "control"):
        assert lat[(server, "*")]["calls"] > 0
        assert lat[(server, "*")]["median_ms"] <= lat[(server, "*")]["p95_ms"]
    assert ("control", "insert_row") in lat and ("treatment", "create_purchase_order") in lat
    report = Path(result["report"]).read_text()
    assert report.startswith("# anerp evaluation report")
    assert "## Tool-call latency" in report and "## Tool calls per task" in report
    assert Path(result["summary"]).exists() and Path(result["latency"]).exists()
