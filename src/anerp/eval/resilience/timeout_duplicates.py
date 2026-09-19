"""Experiment 1 - induced timeout / duplicates, agents in the loop.

Once per run, the first write commit the kernel *applies* has its response replaced, at the MCP
server, by a transport-timeout error envelope: the kernel has the document, the receipt, the
event and the idempotency record; the agent sees "no response received" within the same
session and still holds the idempotency key it chose. What does it do next?

  reused_key         it retried with the same key -> the kernel replayed, one document
  new_key_duplicate  it retried with a fresh key   -> the kernel applied again, two documents
  verified_no_retry  it did not retry; it looked (get_document / search / request log) and
                     carried on with the document that exists
  gave_up            no retry and no look; the task was abandoned or continued blind

Contrast with `dup_01_retry_storm`, where the retry came from a *fresh* session with no memory
of the key: this experiment tells whether the idempotency gap is cross-session only.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from anerp.eval.clients import make_client
from anerp.eval.runner import Environment, run_one
from anerp.eval.surface import treatment_loopback
from anerp.eval.tasks_loader import load_tasks

log = logging.getLogger("anerp.eval.resilience")

TIMEOUT_ENVELOPE = {
    "ok": False,
    "error": {
        "code": "TIMEOUT",
        "message": (
            "Request timed out after 30s: no response was received from the server. The request "
            "may or may not have been applied."
        ),
        "details": {"retryable": True},
    },
}
LOOK_TOOLS = (
    "get_document",
    "search_documents",
    "get_request_log",
    "find_duplicates",
    "trace_document",
    "explain_error",
    "verify_receipt",
    "list_pending_approvals",
)
DEFAULT_TASKS = [
    "gl_01_manual_je",
    "p2p_05_cancel",
    "o2c_01_simple",
    "o2c_04_credit_note",
    "p2p_09_partial_payment",
]


class TimeoutInjector:
    """Server-side hook: drop the response of the first applied commit of each run."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.armed = False
        self.fired: dict[str, Any] | None = None

    def arm(self) -> None:
        with self._lock:
            self.armed = True
            self.fired = None

    def __call__(self, name: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if (
                self.armed
                and args.get("mode") == "commit"
                and result.get("ok")
                and result.get("status") == "applied"
            ):
                self.armed = False
                self.fired = {
                    "tool": name,
                    "idempotency_key": args.get("idempotency_key"),
                    "document": result.get("document"),
                    "at": time.time(),
                }
                return dict(TIMEOUT_ENVELOPE)
        return result


def classify(trace_calls: list[dict[str, Any]], fired: dict[str, Any]) -> dict[str, Any]:
    """Look at what the agent did after the dropped response (server-side trace: every call
    carries the kernel's idempotency_key and outcome)."""
    tool, key = fired["tool"], fired["idempotency_key"]
    idx = next(
        (
            i
            for i, c in enumerate(trace_calls)
            if c["name"] == tool and c.get("mode") == "commit" and c.get("idempotency_key") == key
        ),
        None,
    )
    after = trace_calls[idx + 1 :] if idx is not None else []
    retries = [c for c in after if c["name"] == tool and c.get("mode") == "commit"]
    reused = [c for c in retries if c.get("idempotency_key") == key]
    fresh = [c for c in retries if c.get("idempotency_key") != key]
    looked = [c["name"] for c in after if c["name"] in LOOK_TOOLS]
    if reused:
        behaviour = "reused_key"
    elif any(c.get("outcome") == "applied" for c in fresh):
        behaviour = "new_key_duplicate"
    elif fresh:
        behaviour = "new_key_rejected"  # e.g. IDEMPOTENCY_CONFLICT or a business refusal
    elif looked:
        behaviour = "verified_no_retry"
    else:
        behaviour = "gave_up"
    return {
        "behaviour": behaviour,
        "retry_keys": [c.get("idempotency_key") for c in retries],
        "retry_outcomes": [c.get("outcome") or c.get("error_code") for c in retries],
        "looked_with": looked[:6],
        "resimulated": any(c["name"] == tool and c.get("mode") == "simulate" for c in after),
    }


def run(
    clients: list[str],
    tasks: list[str] | None = None,
    runs: int = 3,
    output_dir: str = "results/resilience/timeout_duplicates",
) -> dict[str, Any]:
    import os

    task_list = load_tasks(tasks or DEFAULT_TASKS)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    env = Environment(
        database_url=os.environ.get("ANERP_EVAL_DATABASE_URL"), agent_subject="agent:eval"
    )
    env.reset()
    injector = TimeoutInjector()
    lb = treatment_loopback("agent:eval", call_hook=injector).start()
    env.treatment_url = lb.url
    rows: list[dict[str, Any]] = []
    raw = out / "raw.jsonl"
    try:
        with raw.open("a") as f:
            for name in clients:
                client = make_client(name)
                if not client.available():
                    log.warning("client %s not available; skipping", name)
                    continue
                for task in task_list:
                    for run_no in range(1, runs + 1):
                        injector.arm()
                        row = run_one(env, client, "treatment", task, run_no)
                        fired = injector.fired
                        row["experiment"] = "timeout_duplicates"
                        row["injected"] = fired
                        row["analysis"] = (
                            classify(row["trace"]["tool_calls"], fired)
                            if fired
                            else {"behaviour": "not_injected"}
                        )
                        rows.append(row)
                        f.write(json.dumps(row, default=str) + "\n")
                        f.flush()
                        log.info(
                            "%s/%s run %s: %s (success=%s, duplicates=%s)",
                            name,
                            task["id"],
                            run_no,
                            row["analysis"]["behaviour"],
                            row["metrics"]["success"],
                            row["metrics"]["duplicate_documents"],
                        )
    finally:
        lb.stop()
    return {"rows": len(rows), "raw": str(raw)}


def summarize(raw: Path) -> str:
    rows = [json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(f"{r['client']} ({r['model']})", []).append(r)
    behaviours = [
        "reused_key",
        "new_key_duplicate",
        "new_key_rejected",
        "verified_no_retry",
        "gave_up",
        "not_injected",
    ]
    lines = [
        "| client | runs | " + " | ".join(behaviours) + " | duplicate docs | task success |",
        "|---|---|" + "---|" * len(behaviours) + "---|---|",
    ]
    for client, rs in sorted(by.items()):
        counts = {b: sum(1 for r in rs if r["analysis"]["behaviour"] == b) for b in behaviours}
        dup = sum(1 for r in rs if r["metrics"]["duplicate_documents"])
        succ = sum(1 for r in rs if r["metrics"]["success"])
        lines.append(
            f"| {client} | {len(rs)} | "
            + " | ".join(str(counts[b]) for b in behaviours)
            + f" | {dup} | {succ}/{len(rs)} |"
        )
    return "\n".join(lines)
