"""summary.csv, latency.csv and report.md from raw.jsonl (plus an optional matplotlib plot)."""

from __future__ import annotations

import contextlib
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

COLUMNS = [
    "server",
    "client",
    "model",
    "task",
    "runs",
    "success_rate",
    "step_limit_rate",
    "client_error_rate",
    "failure_rate",
    "unsafe_write_rate",
    "simulate_before_commit_rate",
    "duplicate_document_rate",
    "recovery_success_rate",
    "avg_tool_calls",
    "avg_input_tokens",
    "avg_output_tokens",
    "avg_wall_s",
    "tb_integrity",
    "outcomes",
]


LATENCY_COLUMNS = ["server", "client", "tool", "calls", "median_ms", "p95_ms", "mean_ms", "max_ms"]


def _mean(values: list[Any]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)) - 1, 0)]


def latency(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-tool-call latency per server x client, overall (`tool` = "*") and per tool name.
    Measured where the trace was taken: client-side for in-process clients, server-side for SDK
    adapters (`runner._server_side_trace`), so both arms are measured the same way in one run."""
    samples: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for r in rows:
        for c in r["trace"]["tool_calls"]:
            ms = float(c.get("latency_ms") or 0.0)
            samples[(r["server"], r["client"], "*")].append(ms)
            samples[(r["server"], r["client"], c["name"])].append(ms)
    return [
        {
            "server": server,
            "client": client,
            "tool": tool,
            "calls": len(vals),
            "median_ms": round(median(vals), 1),
            "p95_ms": round(_percentile(vals, 95), 1),
            "mean_ms": round(mean(vals), 1),
            "max_ms": round(max(vals), 1),
        }
        for (server, client, tool), vals in sorted(
            samples.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] != "*", kv[0][2])
        )
    ]


def _category(x: dict[str, Any]) -> str:
    """Outcome category, derived for rows written before it was recorded."""
    if x.get("outcome_category"):
        return str(x["outcome_category"])
    if x["success"]:
        return "success"
    if x.get("error") == "max_steps":
        return "step_limit"
    return "client_error" if x.get("error") else "failure"


def _outcomes(metrics: list[dict[str, Any]]) -> str | None:
    """`closed=2;asked_for_confirmation=1` for tasks with alternative outcomes, else None."""
    counts: dict[str, int] = defaultdict(int)
    for x in metrics:
        if x.get("outcome"):
            counts[x["outcome"]] += 1
    return ";".join(f"{k}={v}" for k, v in sorted(counts.items())) or None


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["server"], r["client"], r["task"])].append(r)
    out = []
    for (server, client, task), items in sorted(groups.items()):
        m = [i["metrics"] for i in items]
        recovery = [i["metrics"]["success"] for i in items if i["metrics"]["recovery_task"]]
        out.append(
            {
                "server": server,
                "client": client,
                "model": next((i.get("model") for i in items if i.get("model")), None),
                "task": task,
                "runs": len(items),
                "success_rate": _mean([x["success"] for x in m]),
                "step_limit_rate": _mean([_category(x) == "step_limit" for x in m]),
                "client_error_rate": _mean([_category(x) == "client_error" for x in m]),
                "failure_rate": _mean([_category(x) == "failure" for x in m]),
                "unsafe_write_rate": _mean([1.0 if x["unsafe_writes"] else 0.0 for x in m]),
                "simulate_before_commit_rate": _mean([x["simulate_before_commit_rate"] for x in m]),
                "duplicate_document_rate": _mean(
                    [1.0 if x["duplicate_documents"] else 0.0 for x in m]
                ),
                "recovery_success_rate": _mean(recovery) if recovery else None,
                "avg_tool_calls": _mean([x["tool_calls"] for x in m]),
                "avg_input_tokens": _mean([x["input_tokens"] for x in m]),
                "avg_output_tokens": _mean([x["output_tokens"] for x in m]),
                "avg_wall_s": _mean([x["wall_s"] for x in m]),
                "tb_integrity": _mean([1.0 if x["tb_balanced"] else 0.0 for x in m]),
                "outcomes": _outcomes(m),
            }
        )
    return out


def write_outputs(run_dir: Path, rows: list[dict[str, Any]]) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    with (run_dir / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(summary)
    with (run_dir / "latency.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LATENCY_COLUMNS)
        w.writeheader()
        w.writerows(latency(rows))
    (run_dir / "report.md").write_text(render_report(summary, rows))
    with contextlib.suppress(Exception):  # plots are optional (matplotlib extra)
        plot(run_dir, summary)
    return {
        "summary": str(run_dir / "summary.csv"),
        "latency": str(run_dir / "latency.csv"),
        "report": str(run_dir / "report.md"),
        "raw": str(run_dir / "raw.jsonl"),
    }


def render_report(summary: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    limits = sorted(
        {int(r["metrics"].get("max_steps") or 0) for r in rows if r["metrics"].get("max_steps")}
    )
    lines = [
        "# anerp evaluation report",
        "",
        f"Runs: {len(rows)}. Grouped per server x client x task (DESIGN.md §14.4). "
        "Outcome categories per run: success (goal met), step-limit (agent exhausted its step limit "
        "before meeting it), client error (vendor rate limit / API rejection / transport), failure "
        "(finished, goal not met)."
        + (f" Step limits in this run: {limits[0]}-{limits[-1]} per round." if limits else ""),
        "",
    ]
    by_sc: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for s in summary:
        by_sc[(s["server"], s["client"])].append(s)
    lines += [
        "## Headline (per server x client, averaged over tasks)",
        "",
        "| server | client | model | tasks | success | step-limit | client error | failure | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (server, client), items in sorted(by_sc.items()):
        lines.append(
            f"| {server} | {client} | {items[0].get('model') or '-'} | {len(items)} | {_mean([i['success_rate'] for i in items])} | {_mean([i['step_limit_rate'] for i in items])} | {_mean([i['client_error_rate'] for i in items])} | {_mean([i['failure_rate'] for i in items])} | {_mean([i['unsafe_write_rate'] for i in items])} | {_mean([i['simulate_before_commit_rate'] for i in items])} | {_mean([i['duplicate_document_rate'] for i in items])} | {_mean([i['recovery_success_rate'] for i in items])} | {_mean([i['avg_tool_calls'] for i in items])} | {_mean([i['avg_wall_s'] for i in items])} | {_mean([i['tb_integrity'] for i in items])} |"
        )
    lines += [
        "",
        "## Per task",
        "",
        "| server | client | task | runs | success | step-limit | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['server']} | {s['client']} | {s['task']} | {s['runs']} | {s['success_rate']} | {s['step_limit_rate']} | {s['unsafe_write_rate']} | {s['simulate_before_commit_rate']} | {s['duplicate_document_rate']} | {s['avg_tool_calls']} | {s['avg_input_tokens']} | {s['avg_output_tokens']} | {s['avg_wall_s']} |"
        )
    lines += ["", "## Tool-call latency (ms, per call)", ""]
    lines += [
        "| server | client | calls | median | p95 | mean | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for lat in latency(rows):
        if lat["tool"] == "*":
            lines.append(
                f"| {lat['server']} | {lat['client']} | {lat['calls']} | {lat['median_ms']} | {lat['p95_ms']} | {lat['mean_ms']} | {lat['max_ms']} |"
            )
    lines += ["", "Per tool name in `latency.csv`.", ""]
    servers = sorted({s["server"] for s in summary})
    clients = sorted({s["client"] for s in summary})
    calls_by = {(s["server"], s["client"], s["task"]): s["avg_tool_calls"] for s in summary}
    for client in clients:
        lines += [
            f"## Tool calls per task ({client}, mean over runs)",
            "",
            "| task | " + " | ".join(servers) + " |",
            "|---|" + "---|" * len(servers),
        ]
        for task in sorted({s["task"] for s in summary if s["client"] == client}):
            cells = [str(calls_by.get((srv, client, task), "-")) for srv in servers]
            lines.append(f"| {task} | " + " | ".join(cells) + " |")
        lines.append("")
    branched = [r for r in rows if r["metrics"].get("outcome") or _has_one_of(r)]
    if branched:
        lines += [
            "## Alternative outcomes (tasks with `one_of` goals)",
            "",
            "| server | client | task | run | outcome |",
            "|---|---|---|---|---|",
        ]
        for r in branched:
            lines.append(
                f"| {r['server']} | {r['client']} | {r['task']} | {r['run']} | {r['metrics'].get('outcome') or 'neither (failed)'} |"
            )
        lines.append("")
    failures = [r for r in rows if not r["metrics"]["success"]]
    if failures:
        lines += ["", "## Failed goal checks", ""]
        for r in failures[:100]:
            bad = [g for g in r["metrics"]["goal"] if not g["ok"]]
            lines.append(
                f"- {r['server']}/{r['client']}/{r['task']} run {r['run']}: "
                + "; ".join(f"{g['check']} got {g['actual']}" for g in bad)
            )
    return "\n".join(lines) + "\n"


def _has_one_of(row: dict[str, Any]) -> bool:
    return any(g.get("check") == "one_of" for g in row["metrics"].get("goal", []))


def plot(run_dir: Path, summary: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_sc: dict[str, list[float]] = defaultdict(list)
    for s in summary:
        if s["success_rate"] is not None:
            by_sc[f"{s['server']}/{s['client']}"].append(s["success_rate"])
    if not by_sc:
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(list(by_sc), [sum(v) / len(v) for v in by_sc.values()])
    ax.set_ylabel("task success rate")
    ax.set_ylim(0, 1)
    plt.xticks(rotation=20, ha="right")
    fig.tight_layout()
    fig.savefig(run_dir / "success.png", dpi=120)
    plt.close(fig)


def load_raw(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
