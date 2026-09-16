# Reproducibility appendix

Everything the paper's numbers depend on, in one place. The results themselves are committed
under `results/` (see `results/README.md` for the tables); this file says exactly what produced
them and how to produce them again.

## Release

| | |
|---|---|
| Release | `v0.2.0` (git tag), GitHub release of the same name |
| Commit | the commit the `v0.2.0` tag points at (`git rev-parse v0.2.0`); the results in `results/` were produced by the commits listed per run below, all ancestors of it |
| Repository | https://github.com/Paulpandian-ai/headless-erp |
| Archive / DOI | Zenodo, minted from the GitHub release - see `CITATION.cff` |
| License | Apache-2.0 |

## Models

Model identifiers are the vendors' API ids at the time of the run and are recorded on every row
of `raw.jsonl` (`model`) and in `summary.csv`.

| adapter | package | model id | tier | list price (2026-09-12, per MTok in / cached in / out) |
|---|---|---|---|---|
| `claude_agent_sdk` | `claude-agent-sdk` (Claude Code CLI) | `claude-sonnet-5` | mid | $2.00 / $0.20 / $10.00 (cache writes 1.25x) |
| `openai_agents_sdk` | `openai-agents` | `gpt-5.6-terra` | mid | $2.00 / $0.20 / $12.00 |
| `google_adk` | `google-adk` 2.9.0 in its own interpreter | `gemini-3.8-flash` | mid | $0.75 / $0.075 / $3.75 |
| `claude_agent_sdk` (reference run only) | | `claude-opus-5` | strongest | $5.00 / $0.50 / $25.00 |

Tier matching: each vendor's current-generation mid-tier model. `gpt-5-mini` and
`gemini-2.5-flash` were considered and rejected as previous-generation. All three run with the
vendors' default sampling and thinking settings through their own agent SDKs; the harness sets
no temperature, effort or thinking parameters (`src/anerp/eval/clients/`). The system prompt is
the same neutral text for every adapter (`clients/base.py:NEUTRAL_SYSTEM_PROMPT`).

## Runs

| results directory | produced by | date (UTC) | code |
|---|---|---|---|
| `matrix-tier-matched` (360 rows) | merged from the runs below with `anerp eval-merge` | 2026-09-16 | `b16fb7c` |
| Claude arms (120 rows) | GitHub Actions run 34699458623, tag `eval-matrix-1` | 2026-09-12 | `ece71e4` |
| OpenAI arms (120 rows) | Actions run 34701393421, tag `eval-matrix-2+openai_agents_sdk+google_adk` | 2026-09-12 | `e820f45` |
| Google treatment at 5x (60 rows) | Actions run 34769057511, tag `eval-matrix-6+google_adk,servers=treatment,step_factor=5` | 2026-09-13 | `b5faa1b` |
| Google control at 5x (60 rows) | Actions runs 34719591684 + 34756636373 (tags `eval-matrix-4+...` and `eval-matrix-5+...`), six 503 dropouts re-run in place with `anerp eval-retry` in a Codespace | 2026-09-12 to 2026-09-16 | `978a3ea`-`b5faa1b` |
| `google-treatment-x1`, `google-control-x1` | the same arms at the task-default step limit (Actions 34710710120 and 34719591684) | 2026-09-12/13 | `6a6524b`+ |
| `claude-both-arms-1run` (40 rows) | Codespace, `anerp eval --clients claude_agent_sdk` | 2026-09-12 | `3fb5c6b` |
| `scripted-both-arms-codespace-pg` (120 rows) | Codespace, `anerp eval --clients scripted` | 2026-09-11 | `e392bae` |
| `dup01-keys` (3 rows) | Codespace, `dup_01_retry_storm` on treatment, keys captured | 2026-09-12 | `3d0493d`+ |

Environment for the Actions runs: `ubuntu-latest`, Python 3.12 via `uv`, a `postgres:17`
service container per job, one job per vendor with the two arms run one after the other.
Codespace runs: the same code against PostgreSQL 17.11 installed with apt on loopback.

## Seed and calendar

Every run starts from the `baseline` fixture (`src/anerp/seed.py`), applied through the
`reset_and_seed` tool before each run: chart of accounts (10 accounts), suppliers ACME and BOLT,
customers NORTH (credit limit 25,000.00) and HARB (5,000.00), four items with opening stock
(VALVE-2IN 5, HOSE-10M 40, FLANGE-4 100, PUMP-SM 0), opening capital 250,000.00, and a
date-relative calendar (`seed.baseline_periods`): the month before last is closed, last month
(which holds the opening entries) and this month are open. For the runs above (September 2026)
that is 2026-07 closed, 2026-08 and 2026-09 open, opening entries dated 2026-08-01. Tasks refer
to the calendar through placeholders (`{previous_period}`, `{closed_period}`, ...), so a re-run
in another month closes a different period but the same *kind* of period.

Policies are `policies/default.yaml` (PO approval threshold 10,000.00; price tolerance 2 % or
50.00; credit limit per customer). The twenty tasks are `src/anerp/eval/tasks/*.yaml`.

## Harness settings that affect the numbers

- **Step limit**: the task's `max_steps` (10-24) per agent round. Its unit is the adapter's
  (`max_turns` for the Claude and OpenAI SDKs, `max_llm_calls` for Google ADK) and so is not
  comparable across vendors. The Google cells were run with `ANERP_EVAL_STEP_FACTOR=5` /
  `ANERP_EVAL_STEP_FACTOR_CONTROL=5` (50-120 per round) so that no run is cut off; the effective
  limit is on every row as `metrics.max_steps`.
- **Retries**: OpenAI client `max_retries=10`; ADK Gemini `HttpRetryOptions(attempts=8)` on
  429/5xx; a run whose client died on a rate limit is repeated from a fresh kernel up to twice
  (`attempts` on the row). A billing 429 is not retried.
- **Human loop**: the harness plays the warehouse on both arms with the task's expected
  quantities (`runner.human_step`).
- **Outcome categories**: success / step_limit / vendor_unavailable / client_error / failure,
  recomputed from each row's `success` and `error`.

## How to re-run

```bash
git checkout v0.2.0
uv sync --all-extras --dev
uv venv .venv-adk --python 3.12 && uv pip install --python .venv-adk/bin/python google-adk "mcp<2"
export ANERP_EVAL_DATABASE_URL=postgresql+psycopg://anerp:anerp@127.0.0.1:5432/anerp_eval   # any Postgres
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=...
export ANERP_ANTHROPIC_MODEL=claude-sonnet-5 ANERP_OPENAI_MODEL=gpt-5.6-terra ANERP_GOOGLE_MODEL=gemini-3.8-flash

# model-free checks (no cost)
uv run --all-extras anerp eval --clients scripted --servers treatment,control --run-id oracle

# one vendor, both arms, 3 runs (run vendors one at a time: a vendor's arms in parallel trip its TPM limit)
uv run --all-extras anerp eval --clients claude_agent_sdk --servers treatment,control --runs 3 --run-id claude
uv run --all-extras anerp eval --clients openai_agents_sdk --servers treatment,control --runs 3 --run-id openai
ANERP_EVAL_STEP_FACTOR=5 uv run --all-extras anerp eval --clients google_adk --servers treatment,control --runs 3 --run-id google

uv run anerp eval-merge results/claude results/openai results/google --run-id matrix
uv run anerp eval-retry results/matrix --categories vendor_unavailable    # if any 503 dropouts
```

On GitHub Actions the same matrix is `.github/workflows/eval.yml`: dispatch it, or push a tag
`eval-matrix-<id>` (options: `+<client>`, `,servers=`, `,runs=`, `,tasks=`, `,step_factor=`,
`,step_factor_control=`). Expect roughly $45 in API spend for the matrix at 2026-09 list prices and
1.5-6 h of wall clock per vendor; Gemini's control arm at 5x is the slow one (about 5 min/run).

Numbers will not reproduce bit-for-bit: the models are non-deterministic, vendor availability
varies (Gemini 503s, tokens-per-minute limits), and the calendar is relative to the date. The
reference points that are deterministic - the scripted oracle's success (treatment 20/20, control
19/20), its tool-call counts, and per-call latency ordering (treatment 5-7 ms median vs control
1.5-2 ms) - should.

## Threats to validity

See DESIGN.md §14.4: vendor dropouts are not random with respect to run length; the step limit's
unit is adapter-specific; the human loop is played by the harness; idempotency keys are client-chosen
(§8.2, the `dup_01` finding).
