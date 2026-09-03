"""Run the evaluation matrix: servers x clients x tasks x runs -> results/<run_id>/."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from anerp.core.ids import utcnow
from anerp.eval.clients import ALL_CLIENTS, make_client
from anerp.eval.clients.base import RunTrace
from anerp.eval.metrics import record_filtered_counts, run_metrics, snapshot
from anerp.eval.surface import ControlSurface, RemoteSurface, ToolSurface, TreatmentSurface
from anerp.eval.tasks_loader import load_tasks

log = logging.getLogger("anerp.eval")


class Environment:
    """Owns a fresh kernel per run: in-process (SQLite memory) or a remote dev deployment."""

    def __init__(self, remote_url: str | None = None, remote_token: str | None = None) -> None:
        self.remote_url = remote_url
        self.remote_token = remote_token

    @property
    def remote(self) -> bool:
        return bool(self.remote_url and self.remote_token)

    def reset(self) -> None:
        if self.remote:
            from anerp.eval.clients.http import call_tool_http

            r = call_tool_http(
                self.remote_url or "",
                self.remote_token or "",
                "reset_and_seed",
                {
                    "mode": "commit",
                    "idempotency_key": f"eval-reset-{uuid.uuid4().hex}",
                    "fixture_name": "baseline",
                    "confirm": "RESET",
                },
            )
            if not r.get("ok"):
                raise RuntimeError(f"remote reset failed: {r}")
            return
        from anerp import db
        from anerp.core.requestlog import request_log, simulations
        from anerp.ledger.receipts import keyring
        from anerp.seed import seed_fixture

        engine = db.make_engine("sqlite://")
        db.set_engine(engine)
        db.init_db(engine)
        keyring.reset()
        request_log.clear()
        simulations.clear()
        with db.session_scope() as s:
            seed_fixture(s, "baseline")

    def admin_query(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.remote:
            from anerp.eval.clients.http import call_tool_http

            r = call_tool_http(self.remote_url or "", self.remote_token or "", name, payload)
        else:
            from anerp.core.dispatch import run_query
            from anerp.core.envelope import Actor

            r = run_query(name, payload, Actor(id="eval:harness", kind="admin"))
        if not r.get("ok"):
            raise RuntimeError(f"{name} failed: {r.get('error')}")
        return dict(r["result"])

    def admin_commit(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = f"eval-setup-{uuid.uuid4().hex}"
        if self.remote:
            from anerp.eval.clients.http import call_tool_http

            r = call_tool_http(
                self.remote_url or "",
                self.remote_token or "",
                tool,
                {**payload, "mode": "commit", "idempotency_key": key},
            )
        else:
            from anerp.core.dispatch import dispatch
            from anerp.core.envelope import Actor, Envelope

            r = dispatch(
                Envelope(
                    tool=tool,
                    mode="commit",
                    idempotency_key=key,
                    actor=Actor(id="eval:harness", kind="human"),
                    payload=payload,
                )
            )
        if not r.get("ok"):
            raise RuntimeError(f"setup {tool} failed: {r.get('error')}")
        return r

    def surface(self, server: str) -> ToolSurface:
        if server == "control":
            if self.remote:
                raise RuntimeError(
                    "the control server runs in-process only (it bypasses the dispatcher)"
                )
            return ControlSurface()
        if self.remote:
            return RemoteSurface(self.remote_url or "", self.remote_token or "")
        return TreatmentSurface()


def _resolve(value: Any, saved: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return saved[value[1:]]
    if isinstance(value, dict):
        return {k: _resolve(v, saved) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, saved) for v in value]
    return value


def apply_setup(env: Environment, task: dict[str, Any]) -> None:
    saved: dict[str, str] = {}
    for step in task.get("setup", []):
        r = env.admin_commit(step["tool"], _resolve(json.loads(json.dumps(step["payload"])), saved))
        if step.get("save_as"):
            saved[step["save_as"]] = r["document"]["number"]


def run_one(
    env: Environment, client: Any, server: str, task: dict[str, Any], run: int
) -> dict[str, Any]:
    env.reset()
    apply_setup(env, task)
    q = env.admin_query
    before = snapshot(q)
    record_filtered_counts(q, task, before)
    surface = env.surface(server)
    t0 = time.perf_counter()
    trace = RunTrace()
    try:
        for _ in range(int(task.get("repeat", 1))):
            part = client.run(
                task["narrative"],
                surface,
                max_steps=task["max_steps"],
                task_id=f"{task['id']}__{run}",
            )
            trace.tool_calls.extend(part.tool_calls)
            trace.input_tokens += part.input_tokens
            trace.output_tokens += part.output_tokens
            trace.steps += part.steps
            trace.final_text = part.final_text
            trace.error = part.error or trace.error
    except Exception as exc:  # noqa: BLE001
        log.exception("client %s failed on %s", client.name, task["id"])
        trace.error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - t0
    metrics = run_metrics(q, task, before, trace, server, wall)
    return {
        "server": server,
        "client": client.name,
        "task": task["id"],
        "run": run,
        "traps": task.get("traps", []),
        "started_at": utcnow().isoformat(),
        "metrics": metrics,
        "trace": trace.as_dict(),
    }


def run_matrix(
    *,
    clients: list[str],
    servers: list[str],
    tasks: list[str] | None,
    runs: int,
    output_dir: str,
    everything: bool = False,
) -> dict[str, Any]:
    from anerp.eval.report import write_outputs

    remote_url = os.environ.get("ANERP_URL")
    remote_token = os.environ.get("ANERP_ADMIN_TOKEN")
    env = Environment(remote_url if remote_url and remote_token else None, remote_token)
    chosen = []
    for name in ALL_CLIENTS if everything else clients:
        c = make_client(name)
        if c.available():
            chosen.append(c)
        else:
            log.warning("client %s is not available (missing SDK or credentials); skipping", name)
    if not chosen:
        raise SystemExit(
            "no eval client is available: set LLM_PROVIDER / API keys, or use --clients scripted"
        )
    task_list = load_tasks(tasks)
    run_id = utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = Path(output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with (run_dir / "raw.jsonl").open("w") as f:
        for server in servers:
            for client in chosen:
                for task in task_list:
                    for run in range(1, runs + 1):
                        row = run_one(env, client, server, task, run)
                        rows.append(row)
                        f.write(json.dumps(row, default=str) + "\n")
                        f.flush()
                        log.info(
                            "%s/%s/%s run %s: success=%s",
                            server,
                            client.name,
                            task["id"],
                            run,
                            row["metrics"]["success"],
                        )
    files = write_outputs(run_dir, rows)
    return {
        "run_id": run_id,
        "runs": len(rows),
        "successes": sum(1 for r in rows if r["metrics"]["success"]),
        **files,
    }
