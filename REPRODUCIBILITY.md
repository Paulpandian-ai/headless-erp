# Reproducibility appendix

Everything the paper's numbers depend on, in one place. The results themselves are committed
under `results/` (see `results/README.md` for the tables); this file says exactly what produced
them and how to produce them again.

## Release

| | |
|---|---|
| Release | `v0.2.1` (git tag), GitHub release of the same name. `v0.2.0` is the release the matrix and resilience results were produced under; `v0.2.1` adds the framework verification pass, the pre-publication validation record and the harness guard that came out of it, and changes no result |
| Commit | the head of `main` the `v0.2.1` tag points at (`git rev-parse v0.2.1^{}`); the results were produced at `v0.2.0` (`1024788`), an ancestor of it; every result in `results/`, the resilience experiments included, was produced by the commits listed per run below, all ancestors of it |
| Repository | https://github.com/Paulpandian-ai/headless-erp |
| Archive / DOI | Zenodo concept DOI, always the latest version: https://doi.org/10.5281/zenodo.22848737. Version DOIs: v0.2.0 https://doi.org/10.5281/zenodo.22848738; v0.2.1 PENDING_V021_DOI |
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

**Model availability, re-checked 2026-10-03.** All three pinned ids are still served and their
list prices are unchanged, so the published matrix remains reproducible exactly as pinned:
`claude-sonnet-5` and `claude-opus-5` are both still listed by the Anthropic models endpoint;
`gpt-5.6-terra` is still listed and still $2.00 / $0.20 cached / $12.00; `gemini-3.8-flash` is
still listed and still $0.75 / $0.075 / $3.75 — with a published increase to $1.50 / $0.15 / $7.50
from 1 January 2027, so a re-run after that date costs about twice as much on the Google cells.
Two vendors have since shipped newer generations: Anthropic released Claude Sonnet 5.5
(2026-09-28) and Claude Opus 5.5 (2026-09-21), and OpenAI's pricing page now lists a GPT-6 family
(`gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-6.1-sol`). The matrix is **not** re-run for those:
its tier matching is stated as of the run date, and a future tier-matched run would have to decide
the mid-tier of each vendor's then-current generation afresh. Google's `gemini-3.8-flash` remains
the current Flash-line model.

Tier matching: each vendor's current-generation mid-tier model *as of the run date*. `gpt-5-mini`
and `gemini-2.5-flash` were considered and rejected as previous-generation. All three run with the
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
| `resilience/` (commit failure 48 trials x 2 backends; stale writes 8 trials x 2 backends; timeout/duplicates 44 agent runs) | Codespace, `anerp eval-resilience {commit-failure,stale-writes,timeout}`; SQLite in memory and PostgreSQL 17.11 | 2026-09-16 to 2026-09-19 | `c3c3248` |

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
in another month closes a different period but the same *kind* of period. Confirmed by the
October 2026 validation re-run: the same task set exercised 2026-08 as the closed period and
2026-09 as the month to close, and every goal check still passed.

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

Prerequisites on a clean machine: `git`, `uv` (https://docs.astral.sh/uv/), a PostgreSQL server
you can reach, and API keys for the vendors you intend to run. Nothing else: no `ANERP_*`
variables beyond the ones exported below (`ANERP_ENV` is not needed), no `psql` on your own
`PATH`, and no Docker unless you choose option (a) for the database.

A fresh Codespace from this repository already has `uv`, the two virtual environments and
`ANERP_EVAL_DATABASE_URL` from `.devcontainer/devcontainer.json`, but **no database server**: the
URL points at 127.0.0.1:5432 and nothing listens there. It also has **no Docker** — the
docker-in-docker feature was removed because it would not install on the Codespaces base image —
so option (a) below is for machines that have Docker, and in a Codespace you want (b) or (c).
Whichever you choose, the server must be running: a package install starts the cluster once, but
nothing restarts it after the machine or Codespace is restarted.

```bash
git clone https://github.com/Paulpandian-ai/headless-erp && cd headless-erp
git checkout v0.2.1          # or v0.2.0 for the exact tree the results were produced under
uv sync --all-extras --dev
uv venv .venv-adk --python 3.12 && uv pip install --python .venv-adk/bin/python google-adk "mcp<2"

# a Postgres to run against - one of (a), (b) or (c):

# (a) machines with Docker - the repo's compose file: Postgres 17 on 127.0.0.1:5432, user/db anerp/anerp_eval
docker compose up -d --wait

# (b) a package install (this is what a Codespace needs). Note the `su - postgres` form:
#     `sudo -u postgres psql ...` prompts for a password in a non-interactive shell and fails.
sudo apt-get update && sudo apt-get install -y postgresql
sudo service postgresql start                      # also needed after every machine/Codespace restart
sudo su - postgres -c "psql -c \"CREATE USER anerp WITH PASSWORD 'anerp';\" -c 'CREATE DATABASE anerp_eval OWNER anerp;'"

# (c) any hosted Postgres: create an empty database and a role that owns it

pg_isready -h 127.0.0.1 -p 5432                    # must print "accepting connections" before you go on
export ANERP_EVAL_DATABASE_URL=postgresql+psycopg://anerp:anerp@127.0.0.1:5432/anerp_eval   # the harness creates the schema and wipes the database before every run

export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=...   # only for the vendors you run; Google needs a paid-tier project
export ANERP_ANTHROPIC_MODEL=claude-sonnet-5 ANERP_OPENAI_MODEL=gpt-5.6-terra ANERP_GOOGLE_MODEL=gemini-3.8-flash

# model-free check (no cost, ~45 s). Expected: `"runs": 120, "successes": 117` - which is
# treatment 20/20 tasks and control 19/20 (only p2p_04_over_threshold fails, by construction:
# the CRUD surface has no approval request to raise). If the database is unreachable the harness
# stops before the first run and names the variable to fix.
uv run --all-extras anerp eval --clients scripted --servers treatment,control --run-id oracle

# cheapest end-to-end check of a vendor before spending on the matrix (one task, both arms, ~$0.50)
uv run --all-extras anerp eval --clients claude_agent_sdk --servers treatment,control --runs 1 --tasks gl_01_manual_je --run-id smoke

# one vendor, both arms, 3 runs (run vendors one at a time: a vendor's arms in parallel trip its TPM limit)
uv run --all-extras anerp eval --clients claude_agent_sdk --servers treatment,control --runs 3 --run-id claude
uv run --all-extras anerp eval --clients openai_agents_sdk --servers treatment,control --runs 3 --run-id openai
ANERP_EVAL_STEP_FACTOR=5 uv run --all-extras anerp eval --clients google_adk --servers treatment,control --runs 3 --run-id google

uv run anerp eval-merge results/claude results/openai results/google --run-id matrix
uv run anerp eval-retry results/matrix --categories vendor_unavailable    # if any 503 dropouts
```

The resilience experiments (`results/resilience/`) are separate commands. The two deterministic
ones take about a minute each, cost nothing, and run on whichever backend
`ANERP_EVAL_DATABASE_URL` selects - run each twice, once with the variable set and once with it
unset, to cover Postgres and SQLite as the published results do. The agent experiment costs about
$0.12 per run.

```bash
uv run --all-extras anerp eval-resilience commit-failure     # expect "all_pass": true, 24 trials
uv run --all-extras anerp eval-resilience stale-writes       # expect all four scenarios refused on treatment, all four wrong on control
uv run --all-extras anerp eval-resilience timeout --clients claude_agent_sdk --runs 3 --output results/resilience-rerun
```

The published `results/resilience/timeout_duplicates/raw.jsonl` is committed, so the timeout
experiment refuses to write into it and asks for a different `--output`; the deterministic
experiments overwrite their own JSON in place.

On GitHub Actions the same matrix is `.github/workflows/eval.yml`: dispatch it, or push a tag
`eval-matrix-<id>` (options: `+<client>`, `,servers=`, `,runs=`, `,tasks=`, `,step_factor=`,
`,step_factor_control=`). Expect roughly $45 in API spend for the matrix at 2026-09 list prices and
1.5-6 h of wall clock per vendor; Gemini's control arm at 5x is the slow one (about 5 min/run).

Numbers will not reproduce bit-for-bit: the models are non-deterministic, vendor availability
varies (Gemini 503s, tokens-per-minute limits), and the calendar is relative to the date. The
reference points that are deterministic - the scripted oracle's success (treatment 20/20, control
19/20), its tool-call counts, and per-call latency ordering (treatment 5-7 ms median vs control
1-2.5 ms, measured on loopback Postgres 17) - should. The oracle's control-arm call count is
~26 per run from `b5faa1b` on (it waits for the warehouse status line like the agents do);
the committed `scripted-both-arms-codespace-pg` run predates that and shows 25.

## Clean-machine check (2026-09-19)

The procedure above was followed on a fresh clone at `v0.2.0` with a scrubbed environment (no
`ANERP_*` variables except the exported ones, fresh virtual environments, a new empty database)
in this order: sync, ADK venv, oracle run (117/120, 43 s), one-task runs of `claude_agent_sdk`
and `openai_agents_sdk` (2/2 each), the `google_adk` command (ran; the project was refused by
Google with 403 that day), `eval-merge`, `eval-retry`. Every command worked as written. What the
document had assumed without saying, now stated above: that a Postgres server exists at the URL
(a fresh Codespace has none), that a cheap smoke command exists, that `ANERP_ENV` is not needed,
that the Zenodo DOI is not yet minted, and that the resilience experiments live after the tag.

## Pre-publication validation (2026-10-03)

Run against `main` from a fresh clone of the public repository at tag `v0.2.0` (`1024788`), in a
scrubbed environment (`env -i`, only `HOME`, `PATH`, `ANERP_EVAL_DATABASE_URL` and the vendor keys),
with the eval database dropped and recreated empty, so neither the repository's own virtual
environments nor any leftover schema were in play.

**What reproduced.** The model-free check: `"runs": 120, "successes": 117`, treatment 20/20 tasks
and control 19/20 with only `p2p_04_over_threshold` failing, in 42 s; per-call latency medians
6.3 ms treatment against 1.3 ms control, inside the range this appendix states. Both deterministic
resilience experiments, on SQLite and on PostgreSQL 17, byte-equivalent in substance to the
published results: commit failure 24 trials per backend, `all_pass` true; stale writes refused on
all four scenarios on treatment (`STALE_SIMULATION` x3 plus `CREDIT_LIMIT_EXCEEDED`) and wrong on
all four on control with the post-hoc checker flagging none. The agent experiment, re-run from the
clean checkout for two tasks on `claude-sonnet-5` ($0.23), reproduced the published behaviours:
one `reused_key`, one `verified_no_retry`, no duplicates.

**What the pass found, and what was changed.**

| # | Finding | Fix |
|---|---|---|
| 1 | Option (a), `docker compose up -d --wait`, cannot work in a Codespace from this repository: Docker is not installed, because docker-in-docker was removed from the devcontainer | Prerequisites now say so and point a Codespace reader at (b) or (c) |
| 2 | Option (b)'s command failed as written: `sudo -u postgres psql ...` returns "sudo: a terminal is required to read the password" in a non-interactive shell | Replaced with the `sudo su - postgres -c "psql ..."` form that works, with the reason stated |
| 3 | Nothing told the reader to start the server, and nothing restarts it after a Codespace restart — the validation began with port 5432 closed | Added `sudo service postgresql start`, a note that it is needed after every restart, and a `pg_isready` gate before continuing |
| 4 | The appendix gave no commands for reproducing the resilience experiments, although they are listed among the results | Added the three commands with their expected outcomes and costs |
| 5 | Re-running the timeout experiment on a checkout of this repository appended its rows to the committed `raw.jsonl`, silently mixing a re-run's results into the published file | The experiment now refuses to write into a non-empty `raw.jsonl` and names the `--output` option to use (`timeout_duplicates.run`) |
| 6 | The expected output of the model-free check was given as "treatment 20/20, control 19/20", which does not match what the command prints | The expected `runs`/`successes` line is quoted, with the mapping to per-arm task counts |

**What held up.** The harness's own failure message when the database is unreachable names the
variable and points at the eval README, which is what let the pass proceed without guesswork. The
date-relative seed calendar behaved as documented in a different month from the original runs.
Nothing in the pass depended on state left behind by having built the project.

## Threats to validity

See DESIGN.md §14.4: vendor dropouts are not random with respect to run length; the step limit's
unit is adapter-specific; the human loop is played by the harness; idempotency keys are client-chosen
(§8.2, the `dup_01` finding).
