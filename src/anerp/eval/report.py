"""summary.csv and report.md from raw.jsonl (plus an optional matplotlib plot)."""

from __future__ import annotations

import contextlib
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

COLUMNS = [
    "server",
    "client",
    "task",
    "runs",
    "success_rate",
    "unsafe_write_rate",
    "simulate_before_commit_rate",
    "duplicate_document_rate",
    "recovery_success_rate",
    "avg_tool_calls",
    "avg_input_tokens",
    "avg_output_tokens",
    "avg_wall_s",
    "tb_integrity",
]


def _mean(values: list[Any]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


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
                "task": task,
                "runs": len(items),
                "success_rate": _mean([x["success"] for x in m]),
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
    (run_dir / "report.md").write_text(render_report(summary, rows))
    with contextlib.suppress(Exception):  # plots are optional (matplotlib extra)
        plot(run_dir, summary)
    return {
        "summary": str(run_dir / "summary.csv"),
        "report": str(run_dir / "report.md"),
        "raw": str(run_dir / "raw.jsonl"),
    }


def render_report(summary: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# anerp evaluation report",
        "",
        f"Runs: {len(rows)}. Grouped per server x client x task (DESIGN.md §14.4).",
        "",
    ]
    by_sc: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for s in summary:
        by_sc[(s["server"], s["client"])].append(s)
    lines += [
        "## Headline (per server x client, averaged over tasks)",
        "",
        "| server | client | tasks | success | unsafe writes | simulate-before-commit | duplicates | recovery | tool calls | wall s | TB integrity |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (server, client), items in sorted(by_sc.items()):
        lines.append(
            f"| {server} | {client} | {len(items)} | {_mean([i['success_rate'] for i in items])} | {_mean([i['unsafe_write_rate'] for i in items])} | {_mean([i['simulate_before_commit_rate'] for i in items])} | {_mean([i['duplicate_document_rate'] for i in items])} | {_mean([i['recovery_success_rate'] for i in items])} | {_mean([i['avg_tool_calls'] for i in items])} | {_mean([i['avg_wall_s'] for i in items])} | {_mean([i['tb_integrity'] for i in items])} |"
        )
    lines += [
        "",
        "## Per task",
        "",
        "| server | client | task | runs | success | unsafe | sim-before-commit | dup | calls | in tok | out tok | wall s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['server']} | {s['client']} | {s['task']} | {s['runs']} | {s['success_rate']} | {s['unsafe_write_rate']} | {s['simulate_before_commit_rate']} | {s['duplicate_document_rate']} | {s['avg_tool_calls']} | {s['avg_input_tokens']} | {s['avg_output_tokens']} | {s['avg_wall_s']} |"
        )
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
