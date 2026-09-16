# results/

Evaluation outputs land here as `results/<run_id>/raw.jsonl`, `summary.csv`, `latency.csv` and
`report.md` (DESIGN.md §14.4). Everything except this file is gitignored; `eval.yml` uploads runs
as workflow artifacts and can commit a `summary.csv` on request. Runs kept in the repo are
force-added and named below.

| run | what |
|---|---|
| `scripted-both-arms-codespace-pg` | the deterministic oracle on both arms, all 20 tasks x 3 runs, no model; apt Postgres 17 on loopback in a Codespace. Tool-call latency median/p95 per arm and per-task call counts in `report.md` / `latency.csv`. |
| `claude-both-arms-1run` | reduced matrix: `claude_agent_sdk` (claude-opus-5) on both arms, 20 tasks x 1 run, apt Postgres 17 on loopback in a Codespace. Vendor-reported cost $15.58 (treatment $8.89, control $6.69). The two arms were produced by separate `anerp eval` invocations (`--servers treatment` / `--servers control`, same code and database) and merged into one `raw.jsonl` before `write_outputs`; the control arm ran first, the treatment arm was re-run after a session restart lost the first copy. |
| `matrix-tier-matched` | the paper's matrix at the mid tier: `claude-sonnet-5`, `gpt-5.6-terra`, `gemini-3.8-flash`, both arms, 20 tasks x 3 runs (360 rows), on GitHub Actions (`eval.yml`, Postgres 17 service containers). Merged with `anerp eval-merge` from Actions runs 34699458623 (Claude; its OpenAI and Google arms were lost to a 500K-TPM limit and Gemini 503s) 34701393421 (OpenAI, after the retry fixes), 34710710120 (Google treatment, after the retry fixes and the `describe_tool` `$ref` fix) 34719591684 + 34756636373 (Google control at 5x the per-round step limit) and 34769057511 (Google treatment at 5x), so both Google arms share one constraint and no run is cut off. |
| `google-{treatment,control}-x1` / `-x5` | gemini-3.8-flash at the task-default step limit and at 5x. Control: 7/60 (50 cut off) vs 36/60 (none cut off; six 503 dropouts re-run in place with `anerp eval-retry`). Treatment: 54/60 (8 cut off) vs 56/60 (none). The matrix carries the x5 arms. |
| `dup01-keys` | dup_01_retry_storm on treatment for all three vendors with the idempotency key, simulation id and kernel outcome recorded per commit: every retry minted a different key. |

The final numbers are copied below so they can be read without opening `raw.jsonl`; `REPRODUCIBILITY.md` at the repo root records the exact commit, model identifiers, dates, seed and how to re-run.

## Final matrix (`matrix-tier-matched`)

claude-sonnet-5 / gpt-5.6-terra / gemini-3.8-flash; both arms; 20 tasks x 3 runs per cell (360 rows). Both arms run on one kernel in the harness process against one Postgres 17; they differ only in the tool surface. Runs: 2026-09-12 (Claude, OpenAI, Google treatment at the task-default step limit), 2026-09-13 to 2026-09-16 (Google arms at 5x the step limit). Outcome categories: success (goal met), step_limit (budget exhausted before the goal), vendor_unavailable (503/overloaded after every retry), client_error (rate limit / API rejection / transport), failure (finished, goal not met).

### Headline per server x model (mean over tasks)

| server | model | step limit / round | success | step_limit | vendor_unavailable | client_error | failure | unsafe writes | sim->commit | duplicates | recovery | calls/run | wall s/run | TB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| control | claude-sonnet-5 | 10-24 (task default) | 0.650 | 0.000 | 0.000 | 0.000 | 0.350 | 0.033 | - | 0.000 | 0.667 | 27.6 | 77 | 1.000 |
| control | gemini-3.8-flash | 50-120 (x5) | 0.600 | 0.000 | 0.000 | 0.000 | 0.400 | 0.000 | - | 0.000 | 0.333 | 52.1 | 298 | 1.000 |
| control | gpt-5.6-terra | 10-24 (task default) | 0.417 | 0.000 | 0.000 | 0.000 | 0.583 | 0.000 | - | 0.000 | 0.111 | 18.4 | 20 | 1.000 |
| treatment | claude-sonnet-5 | 10-24 (task default) | 0.950 | 0.000 | 0.000 | 0.000 | 0.050 | 0.000 | 1.000 | 0.050 | 1.000 | 9.3 | 38 | 1.000 |
| treatment | gemini-3.8-flash | 50-120 (x5) | 0.933 | 0.000 | 0.000 | 0.000 | 0.067 | 0.000 | 1.000 | 0.033 | 0.778 | 16.6 | 86 | 1.000 |
| treatment | gpt-5.6-terra | 10-24 (task default) | 0.950 | 0.000 | 0.000 | 0.000 | 0.050 | 0.000 | 0.995 | 0.050 | 1.000 | 7.7 | 18 | 1.000 |

Trial-balance integrity is 1.0 in every cell. The step limit's unit differs by adapter (turns for the Claude and OpenAI SDKs, LLM calls for Google ADK) and is not comparable across vendors; the Google cells run at 5x so that no run is cut off (DESIGN.md §14.3).

### Task success per cell (successes out of 3 runs)

Note `dup_01_retry_storm`: 3/3 on every control cell and 0-1/3 on treatment. The CRUD surface makes the agent read the table before inserting, so it finds the first order; on the agent-native surface every retry minted a fresh idempotency key (see the key table below).

| task | T sonnet-5 | T gpt-5.6-terra | T gemini-3.8-flash | C sonnet-5 | C gpt-5.6-terra | C gemini-3.8-flash |
|---|---|---|---|---|---|---|
| close_01_clean | 3 | 3 | 3 | 3 | 3 | 3 |
| close_02_blocked | 3 | 3 | 3 | 3 | 3 | 3 |
| dup_01_retry_storm | 0 | 0 | 1 | 3 | 3 | 3 |
| gl_01_manual_je | 3 | 3 | 3 | 3 | 3 | 3 |
| gl_02_reverse_je | 3 | 3 | 3 | 2 | 0 | 0 |
| gl_03_closed_period | 3 | 3 | 3 | 3 | 3 | 3 |
| o2c_01_simple | 3 | 3 | 3 | 0 | 0 | 0 |
| o2c_02_credit_limit | 3 | 3 | 3 | 3 | 3 | 3 |
| o2c_03_partial_ship | 3 | 3 | 3 | 0 | 0 | 0 |
| o2c_04_credit_note | 3 | 3 | 3 | 3 | 1 | 3 |
| o2c_05_out_of_stock | 3 | 3 | 3 | 3 | 0 | 3 |
| o2c_06_payment_reversal | 3 | 3 | 3 | 1 | 0 | 3 |
| p2p_01_simple | 3 | 3 | 3 | 0 | 0 | 0 |
| p2p_02_partial_receipt | 3 | 3 | 3 | 0 | 0 | 0 |
| p2p_04_over_threshold | 3 | 3 | 3 | 0 | 0 | 0 |
| p2p_05_cancel | 3 | 3 | 3 | 3 | 2 | 3 |
| p2p_06_price_variance_5pct | 3 | 3 | 3 | 3 | 3 | 3 |
| p2p_07_variance_within_tolerance | 3 | 3 | 3 | 3 | 0 | 3 |
| p2p_08_reverse_wrong_grn | 3 | 3 | 1 | 3 | 1 | 0 |
| p2p_09_partial_payment | 3 | 3 | 3 | 0 | 0 | 0 |

T = treatment (agent-native surface), C = control (CRUD baseline).

### Tool-call latency (ms per call, measured server-side)

| server | model | calls | median | p95 | mean | max |
|---|---|---|---|---|---|---|
| control | claude-sonnet-5 | 1658 | 1.7 | 3.6 | 2.0 | 68.8 |
| control | gemini-3.8-flash | 3128 | 1.9 | 5.0 | 2.4 | 112.7 |
| control | gpt-5.6-terra | 1103 | 1.5 | 2.2 | 1.6 | 9.8 |
| treatment | claude-sonnet-5 | 557 | 6.5 | 22.1 | 8.7 | 153.3 |
| treatment | gemini-3.8-flash | 993 | 5.9 | 21.5 | 7.0 | 90.9 |
| treatment | gpt-5.6-terra | 459 | 6.7 | 22.2 | 9.3 | 27.3 |

### Cost

| model | server | input MTok | cached | output kTok | cost | basis |
|---|---|---|---|---|---|---|
| claude-sonnet-5 | control | 10.00 | 90% | 448 | $8.83 | vendor-reported |
| claude-sonnet-5 | treatment | 23.17 | 96% | 181 | $8.82 | vendor-reported |
| gemini-3.8-flash | control | 112.26 | 88% | 1373 | $22.77 | list price x tokens |
| gemini-3.8-flash | treatment | 37.35 | 87% | 261 | $6.99 | list price x tokens |
| gpt-5.6-terra | control | 3.00 | 86% | 74 | $2.23 | list price x tokens |
| gpt-5.6-terra | treatment | 10.16 | 79% | 32 | $6.18 | list price x tokens |

Usable matrix: $55.82. Discarded attempts (throttled arms, pre-fix Google runs, default-limit Google arms, dropout retries) add roughly $50; 429/503 requests are not billed. List prices as of 2026-09-12: Sonnet 5 $2/$0.20 cached/$10 out, cache writes 1.25x; gpt-5.6-terra $2/$0.20/$12; gemini-3.8-flash $0.75/$0.075/$3.75 per MTok.

### close_01_clean: branch taken

| server | model | closed | asked_for_confirmation | neither |
|---|---|---|---|---|
| control | claude-sonnet-5 | 3 | 0 | 0 |
| control | gemini-3.8-flash | 3 | 0 | 0 |
| control | gpt-5.6-terra | 3 | 0 | 0 |
| treatment | claude-sonnet-5 | 3 | 0 | 0 |
| treatment | gemini-3.8-flash | 3 | 0 | 0 |
| treatment | gpt-5.6-terra | 3 | 0 | 0 |

### Google arms at the task-default step limit vs 5x

| arm | limit / round | hit the limit | success | step_limit | vendor_unavailable | failure | calls/run | wall s/run |
|---|---|---|---|---|---|---|---|---|
| treatment | 10-24 (default) | 8 | 54/60 | 2 | 0 | 4 | 17 | 45 |
| treatment | 50-120 (x5) | 0 | 56/60 | 0 | 0 | 4 | 17 | 86 |
| control | 10-24 (default) | 50 | 7/60 | 50 | 0 | 3 | 27 | 78 |
| control | 50-120 (x5) | 0 | 36/60 | 0 | 0 | 24 | 52 | 298 |

Google control at 5x had 6 vendor_unavailable dropouts before the re-run (34/60 = 0.567 over all runs vs 34/54 = 0.630 over completed runs); they were re-run in place with `anerp eval-retry` (2 successes, 4 failures; two dropped again once). Dropouts arrived 16-69 calls into long control runs, so they are not random with respect to run length (DESIGN.md §14.4).

### dup_01_retry_storm on treatment: the two commits (`dup01-keys`)

| model | commit | idempotency_key | kernel outcome |
|---|---|---|---|
| claude-sonnet-5 | 1 | `po-bolt-hose10m-20-20260912-01` | applied |
| claude-sonnet-5 | 2 | `po-bolt-hose10m-20-20260912` | applied |
| gpt-5.6-terra | 1 | `mgr-order-bolt-hose-20260912-001` | applied |
| gpt-5.6-terra | 2 | `order-bolt-hose10m-20-20260912` | applied |
| gemini-3.8-flash | 1 | `po-bolt-hose10m-001` | applied |
| gemini-3.8-flash | 2 | `commit-po-bolt-hose10m-20` | applied |

Same payload both times; every retry minted a different key, so the kernel applied both. Client-chosen keys are not stable across agent sessions: server-enforced idempotency protects retried envelopes, not repeated intent (DESIGN.md §8.2, future work: intent fingerprinting).

### Reference data points

**claude-opus-5, 1 run per task (strongest-model reference; made before the shared human loop and the date-relative close tasks)**

| server | success | unsafe | sim->commit | duplicates | calls/run | wall s/run |
|---|---|---|---|---|---|---|
| control | 0.550 | 0.000 | - | 0.000 | 25.300 | 80.484 |
| treatment | 1.000 | 0.000 | 1.000 | 0.000 | 16.000 | 53.148 |

**scripted oracle, 3 runs per task (model-free floor; the control script hand-implements the kernel's bookkeeping, so its 19/20 is a ceiling for a CRUD surface)**

| server | success | unsafe | sim->commit | duplicates | calls/run | wall s/run |
|---|---|---|---|---|---|---|
| control | 0.950 | 0.000 | - | 0.000 | 25.000 | 0.095 |
| treatment | 1.000 | 0.000 | 1.000 | 0.000 | 6.400 | 0.088 |

