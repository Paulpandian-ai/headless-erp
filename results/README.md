# results/

Evaluation outputs land here as `results/<run_id>/raw.jsonl`, `summary.csv`, `latency.csv` and
`report.md` (DESIGN.md §14.4). Everything except this file is gitignored; `eval.yml` uploads runs
as workflow artifacts and can commit a `summary.csv` on request. Runs kept in the repo are
force-added and named below.

| run | what |
|---|---|
| `scripted-both-arms-codespace-pg` | the deterministic oracle on both arms, all 20 tasks x 3 runs, no model; apt Postgres 17 on loopback in a Codespace. Tool-call latency median/p95 per arm and per-task call counts in `report.md` / `latency.csv`. |
| `claude-both-arms-1run` | reduced matrix: `claude_agent_sdk` (claude-opus-5) on both arms, 20 tasks x 1 run, apt Postgres 17 on loopback in a Codespace. Vendor-reported cost $15.58 (treatment $8.89, control $6.69). The two arms were produced by separate `anerp eval` invocations (`--servers treatment` / `--servers control`, same code and database) and merged into one `raw.jsonl` before `write_outputs`; the control arm ran first, the treatment arm was re-run after a session restart lost the first copy. |
| `matrix-tier-matched` | the paper's matrix at the mid tier: `claude-sonnet-5`, `gpt-5.6-terra`, `gemini-3.8-flash`, both arms, 20 tasks x 3 runs (360 rows), on GitHub Actions (`eval.yml`, Postgres 17 service containers). Merged with `anerp eval-merge` from Actions runs 34699458623 (Claude; its OpenAI and Google arms were lost to a 500K-TPM limit and Gemini 503s) 34701393421 (OpenAI, after the retry fixes) and 34710710120 (Google, after the retry fixes and the `describe_tool` `$ref` fix). |
