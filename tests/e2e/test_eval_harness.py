"""The eval harness end to end with the deterministic `scripted` client: every task's goal checker
must pass on the treatment server for a correct agent, and the control surface must work."""

from __future__ import annotations

from pathlib import Path

from anerp.eval.clients.scripted import ScriptedClient
from anerp.eval.crud_server import crud_call, crud_tools
from anerp.eval.report import load_raw, summarize
from anerp.eval.runner import Environment, run_matrix, run_one
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
        assert m["simulate_before_commit_rate"] in (None, 1.0), task["id"]
    assert not failures, failures


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
        servers=["treatment"],
        tasks=["p2p_01_simple", "dup_01_retry_storm"],
        runs=2,
        output_dir=str(tmp_path),
    )
    assert result["runs"] == 4 and result["successes"] == 4
    raw = load_raw(Path(result["raw"]))
    summary = summarize(raw)
    assert summary[0]["success_rate"] == 1.0 and summary[0]["simulate_before_commit_rate"] == 1.0
    assert (Path(result["report"])).read_text().startswith("# anerp evaluation report")
    assert Path(result["summary"]).exists()
