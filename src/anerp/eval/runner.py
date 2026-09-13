"""Run the evaluation matrix: servers x clients x tasks x runs -> results/<run_id>/."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from anerp.core.ids import utcnow
from anerp.eval.clients import ALL_CLIENTS, make_client
from anerp.eval.clients.base import RunTrace, ToolCallRecord
from anerp.eval.metrics import record_filtered_counts, run_metrics, snapshot
from anerp.eval.surface import (
    EVAL_AGENT_SCOPES,
    ControlSurface,
    LoopbackMcp,
    RemoteSurface,
    ToolSurface,
    TreatmentSurface,
    control_loopback,
    treatment_loopback,
)
from anerp.eval.tasks_loader import load_tasks

log = logging.getLogger("anerp.eval")


class Environment:
    """Owns a fresh kernel per run.

    Local (the default, and the only configuration where treatment and control are comparable):
    one database for both arms - `ANERP_EVAL_DATABASE_URL` (any Postgres) or SQLite in memory -
    reset through the same `reset_and_seed` tool before every run, with both tool surfaces served
    from this process on loopback ports (`treatment_url`, `control_url`) for SDK clients.

    Remote (`ANERP_URL` + `ANERP_ADMIN_TOKEN`, treatment only): a deployed anerp reached with a
    scoped `agent_token`; the admin token stays with the harness for reset, setup and inspection.
    """

    def __init__(
        self,
        remote_url: str | None = None,
        remote_token: str | None = None,
        agent_token: str | None = None,
        agent_subject: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.remote_url = remote_url
        self.remote_token = remote_token
        self.agent_token = agent_token or remote_token
        self.agent_subject = agent_subject
        self.database_url = database_url or "sqlite://"
        self.treatment_url: str | None = None
        self.control_url: str | None = None
        self._engine: Any = None

    @property
    def remote(self) -> bool:
        return bool(self.remote_url and self.remote_token)

    @property
    def backend(self) -> str:
        if self.remote:
            return f"remote {self.remote_url}"
        return (
            "sqlite memory"
            if self.database_url == "sqlite://"
            else self.database_url.split("@")[-1]
        )

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

        if self.database_url == "sqlite://":
            from anerp.seed import seed_fixture

            engine = db.make_engine("sqlite://")
            db.set_engine(engine)
            db.init_db(engine)
            keyring.reset()
            request_log.clear()
            simulations.clear()
            with db.session_scope() as s:
                seed_fixture(s, "baseline")
            return
        if self._engine is None:  # a persistent database: create the schema once, then reset
            engine = db.make_engine(self.database_url)
            try:
                with engine.connect():
                    pass
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"eval database {self.backend} is not reachable ({type(exc).__name__}). "
                    "Point ANERP_EVAL_DATABASE_URL at a running Postgres (src/anerp/eval/README.md "
                    "lists three ways to get one) or unset it to use SQLite in memory."
                ) from exc
            self._engine = engine
            db.set_engine(self._engine)
            db.init_db(self._engine)
        self.admin_commit("reset_and_seed", {"fixture_name": "baseline", "confirm": "RESET"})

    def admin_query(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.remote:
            from anerp.eval.clients.http import call_tool_http

            r = call_tool_http(self.remote_url or "", self.remote_token or "", name, payload)
        else:
            from anerp.core.dispatch import run_query
            from anerp.core.envelope import Actor, local_principal

            r = run_query(
                name,
                payload,
                Actor(id="eval:harness", kind="admin"),
                principal=local_principal("eval:harness"),
            )
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
            from anerp.core.envelope import Actor, Envelope, local_principal

            r = dispatch(
                Envelope(
                    tool=tool,
                    mode="commit",
                    idempotency_key=key,
                    actor=Actor(id="eval:harness", kind="human"),
                    payload=payload,
                ),
                principal=local_principal("eval:harness"),
            )
        if not r.get("ok"):
            raise RuntimeError(f"setup {tool} failed: {r.get('error')}")
        return r

    def surface(self, server: str, *, over_http: bool = False) -> ToolSurface:
        if server == "control":
            if self.remote:
                raise RuntimeError(
                    "the control server runs in-process only (it bypasses the dispatcher)"
                )
            if over_http:
                if not self.control_url:
                    raise RuntimeError("no loopback control MCP server (Environment.control_url)")
                return RemoteSurface(self.control_url, "none", name="control")
            return ControlSurface()
        if self.remote:
            return RemoteSurface(self.remote_url or "", self.agent_token or "")
        if over_http:
            if not self.treatment_url:
                raise RuntimeError("no loopback treatment MCP server (Environment.treatment_url)")
            return RemoteSurface(self.treatment_url, "none", name="treatment")
        return TreatmentSurface()

    def agent_request_log(self) -> list[dict[str, Any]]:
        """What the kernel recorded for the agent principal since the last reset, oldest first.
        The SDK adapters only see the request side of each tool call; the request log is the
        authoritative source for outcome and error code."""
        if not self.agent_subject:
            return []
        entries: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.admin_query(
                "get_request_log", {"actor": self.agent_subject, "limit": 2000, "offset": offset}
            )["requests"]
            entries.extend(page)
            if len(page) < 2000:
                break
            offset += len(page)
        return list(reversed(entries))


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


def _counted(task: dict[str, Any], expected: dict[str, int]) -> tuple[list[dict[str, Any]], str]:
    """What the warehouse counts for a delivery: the expected quantities unless the task's
    `acceptance` overrides a SKU. Same numbers on both arms."""
    overrides = {o["sku"]: o for o in task.get("acceptance", [])}
    accepted = [
        {
            "sku": sku,
            "qty": overrides.get(sku, {}).get("qty", qty),
            "damaged_qty": overrides.get(sku, {}).get("damaged_qty", 0),
            "note": overrides.get(sku, {}).get("note", ""),
        }
        for sku, qty in expected.items()
    ]
    counts = ", ".join(
        f"{a['sku']} x{a['qty']}" + (f" ({a['damaged_qty']} damaged)" if a["damaged_qty"] else "")
        for a in accepted
    )
    return accepted, counts


def human_step(
    env: Environment,
    task: dict[str, Any],
    server: str = "treatment",
    state: dict[str, Any] | None = None,
) -> list[str]:
    """Play the human in the loop for the kinds the task allows, between agent rounds, on both
    arms with the same information. Treatment: the warehouse counts and accepts deliveries through
    `accept_goods` (which posts the receipt) and an approver approves draft POs. Control: the CRUD
    surface has no approval requests and no tool that posts anything, so the same warehouse count
    is handed to the agent as a plain-text status line for every PO with an outstanding delivery,
    once per PO; recording it is the agent's job, as everything is on that surface. Returns
    human-readable status lines for the agent's next round."""
    updates: list[str] = []
    kinds = task.get("human_loop") or []
    if not kinds:
        return updates
    if server == "control":
        if "goods_acceptance" not in kinds:
            return updates
        reported: set[str] = (state if state is not None else {}).setdefault("reported_pos", set())
        for po in env.admin_query("search_documents", {"type": "PurchaseOrder", "limit": 500})[
            "items"
        ]:
            if po["status"] in ("draft", "cancelled") or po["id"] in reported:
                continue
            doc = env.admin_query("get_document", {"id_or_number": po["id"]})
            if any(g.get("status") != "reversed" for g in doc.get("goods_receipts", [])):
                continue  # a receipt already stands against this PO
            expected = {
                line["sku"]: line["qty"] - line["received_qty"]
                for line in doc.get("lines", [])
                if line["qty"] > line["received_qty"]
            }
            if not expected:
                continue
            reported.add(po["id"])
            _, counts = _counted(task, expected)
            updates.append(
                f"the warehouse counted and accepted the delivery for purchase order {po['number']}: {counts}; no goods receipt has been entered for it yet"
            )
        return updates
    pending = env.admin_query("list_pending_approvals", {})["pending"]
    for req in pending:
        if req["kind"] == "goods_acceptance" and "goods_acceptance" in kinds:
            expected = {
                line["sku"]: int(line["qty"])
                for line in (req.get("payload") or {}).get("lines") or []
            }
            if not expected:
                po = env.admin_query("get_document", {"id_or_number": req["document_id"]})
                expected = {
                    line["sku"]: line["qty"] - line["received_qty"]
                    for line in po["lines"]
                    if line["qty"] > line["received_qty"]
                }
            accepted, counts = _counted(task, expected)
            r = env.admin_commit(
                "accept_goods",
                {
                    "request_id": req["id"],
                    "accepted_lines": accepted,
                    "comment": "counted by the warehouse (eval harness)",
                },
            )
            updates.append(
                f"the warehouse accepted delivery {r['document']['number']} for purchase order {req['document_number']}: {counts}"
            )
        elif req["kind"] == "po_approval" and "po_approval" in kinds:
            env.admin_commit(
                "approve_purchase_order",
                {"po": req["document_id"], "comment": "approved (eval harness)"},
            )
            updates.append(f"purchase order {req['document_number']} was approved")
    return updates


def _merge(trace: RunTrace, part: RunTrace) -> None:
    trace.tool_calls.extend(part.tool_calls)
    trace.input_tokens += part.input_tokens
    trace.output_tokens += part.output_tokens
    trace.steps += part.steps
    trace.final_text = part.final_text
    trace.error = part.error or trace.error
    for k, v in part.extra.items():
        trace.extra[k] = trace.extra.get(k, 0) + v if isinstance(v, int | float) else v


def _server_side_trace(
    env: Environment, server: str, surface: ToolSurface, trace: RunTrace
) -> None:
    """Replace the client-side tool-call list with what the server actually saw when the client
    reached it over HTTP (SDK adapters cannot observe results). Keeps the client-side count."""
    if not isinstance(surface, RemoteSurface):
        return
    if server == "control":
        from anerp.eval.crud_server import drain_call_log

        recorded = [
            ToolCallRecord(c["name"], c["arguments"], c["ok"], None, None, c["latency_ms"])
            for c in drain_call_log()
        ]
    else:
        recorded = [
            ToolCallRecord(
                e["tool"],
                e.get("payload") or {},
                e.get("outcome") != "error",
                e.get("error_code"),
                e.get("mode") if e.get("mode") in ("simulate", "commit") else None,
                float(e.get("latency_ms") or 0.0),
                idempotency_key=e.get("idempotency_key"),
                simulation_id=e.get("simulation_id"),
                outcome=e.get("outcome"),
            )
            for e in env.agent_request_log()
        ]
    trace.extra["client_tool_calls"] = len(trace.tool_calls)
    if recorded or not trace.tool_calls:
        trace.tool_calls = recorded
    else:
        trace.extra["trace_source"] = "client (server log empty)"


def step_limit(task: dict[str, Any], server: str) -> int:
    """The task's `max_steps` scaled by ANERP_EVAL_STEP_FACTOR (both arms) and
    ANERP_EVAL_STEP_FACTOR_<SERVER> (one arm). The limit is per agent round; its unit is the
    adapter's (turns for claude_agent_sdk/openai_agents_sdk, LLM calls for google_adk)."""
    factor = float(os.environ.get("ANERP_EVAL_STEP_FACTOR", "1"))
    factor *= float(os.environ.get(f"ANERP_EVAL_STEP_FACTOR_{server.upper()}", "1"))
    return max(1, int(round(int(task["max_steps"]) * factor)))


RATE_LIMIT_MARKERS = (
    "rate limit",
    "rate_limit",
    "429",
    "resource_exhausted",
    "overloaded",
    "quota",
)
"""Substrings of a client error that mean the vendor throttled us, not that the agent failed."""


NOT_RETRYABLE_MARKERS = ("credits are depleted", "billing", "insufficient_quota", "credit balance")
"""A 429 that means the account is out of money is not throttling; waiting will not help."""


def _rate_limited(error: str | None) -> bool:
    text = (error or "").lower()
    if any(m in text for m in NOT_RETRYABLE_MARKERS):
        return False
    return any(m in text for m in RATE_LIMIT_MARKERS)


def run_one(
    env: Environment, client: Any, server: str, task: dict[str, Any], run: int
) -> dict[str, Any]:
    """One run; repeated from a fresh kernel (up to `ANERP_EVAL_RUN_RETRIES`, default 2, after a
    pause) when the client died on a vendor rate limit, so throttling shows up as `attempts` on
    the row rather than as an agent failure."""
    retries = int(os.environ.get("ANERP_EVAL_RUN_RETRIES", "2"))
    for attempt in range(1, retries + 2):
        row = _run_once(env, client, server, task, run)
        row["attempts"] = attempt
        if not _rate_limited(row["trace"].get("error")) or attempt > retries:
            return row
        pause = 60 * attempt
        log.warning(
            "%s/%s/%s run %s hit a rate limit (attempt %s); retrying in %ss",
            server,
            client.name,
            task["id"],
            run,
            attempt,
            pause,
        )
        time.sleep(pause)
    return row  # pragma: no cover


def _run_once(
    env: Environment, client: Any, server: str, task: dict[str, Any], run: int
) -> dict[str, Any]:
    for attempt in range(3):  # a remote deployment can hiccup; a fresh kernel is all-or-nothing
        try:
            env.reset()
            apply_setup(env, task)
            q = env.admin_query
            before = snapshot(q)
            record_filtered_counts(q, task, before)
            break
        except Exception:  # noqa: BLE001
            if attempt == 2 or not env.remote:
                raise
            log.warning("reset/setup for %s failed (attempt %s); retrying", task["id"], attempt + 1)
            time.sleep(5 * (attempt + 1))
    surface = env.surface(server, over_http=bool(getattr(client, "needs_remote", False)))
    limit = step_limit(task, server)
    if server == "control":
        from anerp.eval.crud_server import drain_call_log

        drain_call_log()
    t0 = time.perf_counter()
    trace = RunTrace()
    rounds = 0
    human_state: dict[str, Any] = {}
    try:
        narrative = task["narrative"]
        for _ in range(int(task.get("repeat", 1))):
            _merge(
                trace,
                client.run(narrative, surface, max_steps=limit, task_id=f"{task['id']}__{run}"),
            )
            rounds += 1
        for _ in range(int(task.get("max_rounds", 3)) - 1):
            updates = human_step(env, task, server, human_state)
            if not updates:
                break
            narrative = f"{task['narrative']} Status update: {'; '.join(updates)}. Continue from there; do not repeat what is already done."
            _merge(
                trace,
                client.run(narrative, surface, max_steps=limit, task_id=f"{task['id']}__{run}"),
            )
            rounds += 1
    except Exception as exc:  # noqa: BLE001
        log.exception("client %s failed on %s", client.name, task["id"])
        trace.error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - t0
    with contextlib.suppress(Exception):
        _server_side_trace(env, server, surface, trace)
    metrics = run_metrics(q, task, before, trace, server, wall)
    metrics["rounds"] = rounds
    metrics["max_steps"] = limit
    return {
        "server": server,
        "client": client.name,
        "model": getattr(client, "model", None),
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
    run_id: str | None = None,
) -> dict[str, Any]:
    """Both arms run against one local kernel (ANERP_EVAL_DATABASE_URL, else SQLite in memory),
    each tool surface served from this process on a loopback port when a client needs HTTP, so
    treatment and control differ only in the tool surface. Setting ANERP_EVAL_REMOTE=1 with
    ANERP_URL and ANERP_ADMIN_TOKEN instead runs the treatment arm against that deployment (the
    agents get a freshly minted, scoped token) - useful for demos, not for the comparison."""
    from anerp.eval.report import write_outputs

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
    run_id = run_id or utcnow().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = Path(output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    over_http = any(getattr(c, "needs_remote", False) for c in chosen)

    agent_subject = "agent:eval"
    local_env = Environment(
        database_url=os.environ.get("ANERP_EVAL_DATABASE_URL"), agent_subject=agent_subject
    )
    remote_env: Environment | None = None
    minted_token_id: str | None = None
    remote_url = os.environ.get("ANERP_URL")
    remote_token = os.environ.get("ANERP_ADMIN_TOKEN")
    if os.environ.get("ANERP_EVAL_REMOTE") == "1" and remote_url and remote_token:
        remote_env = Environment(remote_url, remote_token)
        subject = f"agent:eval-{run_id}"
        minted = remote_env.admin_commit(
            "mint_token", {"subject": subject, "kind": "agent", "scopes": EVAL_AGENT_SCOPES}
        )
        minted_token_id = minted["secret"].get("token_id") or subject
        remote_env = Environment(
            remote_url,
            remote_token,
            agent_token=minted["secret"]["token"],
            agent_subject=subject,
        )
        log.info("treatment arm on %s; minted agent token %s", remote_url, subject)
    loopbacks: list[LoopbackMcp] = []
    if over_http:
        local_env.reset()  # bind the engine before the servers take requests
        if "treatment" in servers and remote_env is None:
            lb = treatment_loopback(agent_subject).start()
            local_env.treatment_url = lb.url
            loopbacks.append(lb)
        if "control" in servers:
            lb = control_loopback().start()
            local_env.control_url = lb.url
            loopbacks.append(lb)
        for lb in loopbacks:
            log.info("%s surface served at %s (kernel: %s)", lb.name, lb.url, local_env.backend)

    rows: list[dict[str, Any]] = []
    try:
        with (run_dir / "raw.jsonl").open("w") as f:
            for server in servers:
                env = remote_env if server == "treatment" and remote_env else local_env
                for client in chosen:
                    for task in task_list:
                        for run in range(1, runs + 1):
                            row = run_one(env, client, server, task, run)
                            row["backend"] = env.backend
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
    finally:
        for lb in loopbacks:
            lb.stop()
        if remote_env and minted_token_id:
            with contextlib.suppress(Exception):
                remote_env.admin_commit(
                    "revoke_token",
                    {"token_id": minted_token_id, "reason": f"eval matrix {run_id} finished"},
                )
    files = write_outputs(run_dir, rows)
    return {
        "run_id": run_id,
        "runs": len(rows),
        "successes": sum(1 for r in rows if r["metrics"]["success"]),
        "backends": sorted({r["backend"] for r in rows}),
        **files,
    }


def retry_rows(run_dir: str, categories: list[str]) -> dict[str, Any]:
    """Re-run, in place, the rows of results/<run_id>/ whose outcome category is in
    `categories` (e.g. vendor_unavailable: the vendor could not serve them), with the same
    client, server, task and run number, then regenerate the outputs. Rows keep their position;
    the replaced row records `retried_from` (the old category) and `attempts`."""
    from anerp.eval.metrics import outcome_category
    from anerp.eval.report import load_raw, write_outputs

    path = Path(run_dir) / "raw.jsonl"
    rows = load_raw(path)
    tasks = {t["id"]: t for t in load_tasks()}
    clients: dict[str, Any] = {}
    local_env = Environment(
        database_url=os.environ.get("ANERP_EVAL_DATABASE_URL"), agent_subject="agent:eval"
    )
    loopbacks: list[LoopbackMcp] = []
    replaced = 0
    try:
        for i, row in enumerate(rows):
            trace = RunTrace(error=row["trace"].get("error"))
            category = outcome_category(bool(row["metrics"]["success"]), trace)
            if category not in categories:
                continue
            client = clients.get(row["client"])
            if client is None:
                client = clients[row["client"]] = make_client(row["client"])
                if not client.available():
                    raise SystemExit(f"client {row['client']} is not available here")
                if getattr(client, "needs_remote", False) and not loopbacks:
                    local_env.reset()
                    for server in sorted({r["server"] for r in rows}):
                        lb = (
                            treatment_loopback("agent:eval")
                            if server == "treatment"
                            else control_loopback()
                        ).start()
                        setattr(local_env, f"{server}_url", lb.url)
                        loopbacks.append(lb)
            log.info(
                "retrying %s/%s/%s run %s (%s)",
                row["server"],
                row["client"],
                row["task"],
                row["run"],
                category,
            )
            new = run_one(local_env, client, row["server"], tasks[row["task"]], int(row["run"]))
            new["backend"] = local_env.backend
            new["retried_from"] = category
            rows[i] = new
            replaced += 1
            with path.open("w") as f:
                for r in rows:
                    f.write(json.dumps(r, default=str) + "\n")
    finally:
        for lb in loopbacks:
            lb.stop()
    files = write_outputs(Path(run_dir), rows)
    return {"run_dir": run_dir, "replaced": replaced, **files}
