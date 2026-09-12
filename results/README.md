# results/

Evaluation outputs land here as `results/<run_id>/raw.jsonl`, `summary.csv`, `latency.csv` and
`report.md` (DESIGN.md §14.4). Everything except this file is gitignored; `eval.yml` uploads runs
as workflow artifacts and can commit a `summary.csv` on request. Runs kept in the repo are
force-added and named below.

| run | what |
|---|---|
| `scripted-both-arms-codespace-pg` | the deterministic oracle on both arms, all 20 tasks x 3 runs, no model; apt Postgres 17 on loopback in a Codespace. Tool-call latency median/p95 per arm and per-task call counts in `report.md` / `latency.csv`. |
