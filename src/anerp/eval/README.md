# Evaluation harness

`anerp.eval` is the paper's data source (DESIGN.md §14): the agent-native tool surface
(**treatment**) against a naive CRUD MCP server over the same tables (**control**,
`crud_server.py`, the only code that bypasses the dispatcher), across three SDK adapters and
twenty tasks, three runs each.

## The comparison is clean by construction

Both arms run **in the harness process against one database**, so they differ in nothing but
the tool surface:

- one kernel database (`ANERP_EVAL_DATABASE_URL`, any Postgres you can reach; SQLite in memory
  if unset), reset through the `reset_and_seed` tool before every run;
- each surface served on a loopback port (`surface.LoopbackMcp`) for the SDK adapters, which
  only speak MCP over streamable HTTP - no network, no deployment, no shared dev database;
- the agents act as `agent:eval` with `surface.EVAL_AGENT_SCOPES` on both arms; admin tools
  are hidden from both listings;
- tool outcomes and error codes come from the kernel's request log (treatment) or an
  in-process call log (control), not from the client, so the unsafe-write and
  simulate-before-commit metrics are the same whichever SDK made the call.

Running the treatment arm against a deployment (`ANERP_EVAL_REMOTE=1` with `ANERP_URL` and
`ANERP_ADMIN_TOKEN`) is for demos only: it mints and revokes a scoped agent token per matrix,
but it confounds latency, cost and error behaviour with the network.

## Setup on a clean machine

```bash
uv sync --all-extras                                   # anerp + the three SDK adapters
uv venv .venv-adk --python 3.12 \
  && uv pip install --python .venv-adk/bin/python google-adk "mcp<2"   # see "google-adk" below
export ANERP_EVAL_DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db>
export ANTHROPIC_API_KEY=… OPENAI_API_KEY=… GOOGLE_API_KEY=…   # only the adapters you run
```

The devcontainer does the first two lines and exports `ANERP_EVAL_DATABASE_URL` pointing at
`127.0.0.1:5432` with the throwaway credentials below; it does not start a database (the
Codespaces base image cannot run docker-in-docker).

### The database

The harness is Postgres-agnostic: it needs one reachable Postgres, named by
`ANERP_EVAL_DATABASE_URL` (`postgresql+psycopg://…`), and creates the schema itself on first
connect. Both arms share it and it is wiped by `reset_and_seed` before every run, so never point
it at a database that holds anything you care about. Three ways to get one:

1. **Docker Compose** (reviewers with Docker): `docker compose up -d --wait` starts Postgres 17
   on `127.0.0.1:5432` with the throwaway loopback-only credentials in `docker-compose.yml`:
   `postgresql+psycopg://anerp:anerp@127.0.0.1:5432/anerp_eval`.
2. **GitHub Actions**: `.github/workflows/eval.yml` runs the matrix against a `postgres:17`
   service container with the same credentials; nothing to set up.
3. **Any other Postgres**: a hosted instance (Railway, Neon, Supabase, RDS …), a package-manager
   install (`apt install postgresql`, `brew install postgresql@17`), or an existing server. Create
   an empty database and a role that owns it, and export its URL. This is how the Codespace
   result in `results/` was produced (apt Postgres 17 on loopback). A hosted instance adds network
   latency to every tool call, on both arms equally.

With the variable unset the harness falls back to SQLite in memory, which is fine for the
checker self-test but not for the paper's numbers (`reset_and_seed`, row locking and the request
log behave differently).

## Running

```bash
uv run --all-extras anerp eval --clients scripted --servers treatment   # checker self-test, no LLM
uv run --all-extras anerp eval \
  --clients claude_agent_sdk,openai_agents_sdk,google_adk \
  --servers treatment,control --tasks all --runs 3 --run-id 2026-09-matrix
```

Outputs land in `results/<run_id>/`: `raw.jsonl` (one row per run with metrics and the full
tool-call trace), `summary.csv` and `report.md` (per server x client x task, the §14.4 metrics),
`latency.csv` (per-tool-call latency median/p95 per server x client, overall and per tool), and
`success.png` when matplotlib is installed. `--tasks p2p_01_simple --runs 1` is a cheap
probe (about $1 per adapter) before the full matrix. Runs on one kernel are sequential; budget
roughly 60-90 s per run.

Models are pinned per adapter and recorded on every row (`model` in `raw.jsonl` and
`summary.csv`): `ANERP_ANTHROPIC_MODEL`, `ANERP_OPENAI_MODEL`, `ANERP_GOOGLE_MODEL`. The local
defaults are each vendor's strongest tier (`claude-opus-5`, `gpt-5`, `gemini-3.1-pro-preview`;
`gemini-2.5-pro` is retired for new users).

## The matrix on GitHub Actions

`.github/workflows/eval.yml` (manual dispatch, or push a tag `eval-matrix-<id>`) runs the
paper's matrix: one job per client (vendor) against its own Postgres service container, the two
arms one after the other - a vendor's arms in parallel double the token rate and trip its
tokens-per-minute limit, while one job for everything would exceed the 6-hour limit - then a
`merge` job that rebuilds `summary.csv`, `latency.csv` and
`report.md` over every row with `anerp eval-merge` and uploads `results/<run_id>/` as an
artifact (`commit_results` also commits it to the branch). Its defaults are the **tier-matched
cross-vendor comparison**: each vendor's current mid-tier model (`claude-sonnet-5`,
`gpt-5.6-terra`, `gemini-3.8-flash`), both arms, all 20 tasks, 3 runs; the model inputs
override the tier. `results/claude-both-arms-1run` (claude-opus-5, one run) is kept as a
separate "strongest model" data point outside that comparison. The three API keys are
repository secrets.

## The human in the loop, on both arms

Tasks with `human_loop: [goods_acceptance]` need a warehouse count. Between agent rounds the
harness plays the warehouse with the same numbers on both arms (`runner.human_step`): on
treatment it accepts the pending `goods_acceptance` request through `accept_goods`, which posts
the receipt, and tells the agent; on control - where there is no request to accept and no tool
that posts anything - it tells the agent the count in the same status line and notes that no
receipt has been entered. Both agents then get the narrative plus the status update for the next
round. Recording the receipt itself on the control arm is part of what that surface costs.

## Periods and the close tasks

The baseline fixture's calendar is relative to the date (`seed.baseline_periods`): the month
before last is closed, last month (with the opening balances) and this month are open.
`close_01_clean`/`close_02_blocked` close **last month** (`{previous_period}`), a finished
period, and `gl_03_closed_period` posts into the closed one (`{closed_period}`). `close_01`
accepts two outcomes (`one_of` in the YAML): the period closed, or left open with the report
asking a human to confirm - an agent that finds the checklist green and stops for sign-off
before an irreversible-looking step is not wrong.

If the database is down the harness stops before the first run with a message pointing here.
A run whose client died on a vendor rate limit is repeated from a fresh kernel after a pause
(`ANERP_EVAL_RUN_RETRIES`, default 2); the row records `attempts`. The OpenAI adapter also
raises its client's retries (`ANERP_OPENAI_MAX_RETRIES`, default 10, honouring `retry-after`)
and the ADK worker retries 429/5xx with exponential backoff (`ANERP_GOOGLE_MAX_RETRIES`,
default 8) - Gemini answers 503 "high demand" for minutes at a time.

### Model-free run on both arms

`--clients scripted --servers treatment,control` runs the deterministic oracle on both surfaces:
on treatment it follows simulate-then-commit; on control (`clients/scripted_crud.py`) it is the
best-case CRUD agent. Both wait for the warehouse's status line like any other agent. No model is called, so it gives a floor for tool calls per task and a
per-call latency comparison of the two surfaces on the same kernel; `report.md` and
`latency.csv` carry the median/p95 per arm and the per-task call counts. It is not an LLM result
and does not go in the paper's matrix.

**Read the control oracle's 19/20 as a ceiling, not a typical result.** The CRUD surface offers
nothing but row access, so the oracle hand-implements the kernel's bookkeeping and policies in
the script itself: document numbering, every journal entry and its lines, open items, stock
movements, line quantities and statuses, the approval threshold, the price tolerance, the credit
limit, the stock check and the closed-period check. It never mistypes a column, never forgets
the GR/IR side of a receipt, and never posts into a closed period. An LLM agent on the same
surface has to discover all of that from column names and gets none of it enforced; the paper's control numbers come from those agents, not from this
script. The one task it cannot pass (`p2p_04`) fails because the CRUD surface has no approval
request to raise, not because the script got it wrong.

## google-adk

`google-adk` depends on `mcp` 1.x while anerp runs on `mcp` 2.x, so the ADK loop runs as a
subprocess (`clients/google_adk_worker.py`, no anerp imports) under its own interpreter:
`.venv-adk/bin/python` by default, or `ANERP_GOOGLE_ADK_PYTHON`. The worker runs with `-P`
because `clients/http.py` would otherwise shadow the standard library's `http` package.

## Clients

| Adapter | Package | Needs |
|---|---|---|
| `claude_agent_sdk` | `claude-agent-sdk` (the `anthropic` extra) | `ANTHROPIC_API_KEY` |
| `openai_agents_sdk` | `openai-agents` (the `openai` extra) | `OPENAI_API_KEY` |
| `google_adk` | `google-adk` in `.venv-adk` | `GOOGLE_API_KEY` (a paid-tier key: Pro models have no free quota) |
| `in_process` | none (uses `LLM_PROVIDER`) | one provider key |
| `scripted` | none | nothing; a deterministic oracle for the checkers, not part of the matrix |

AWS AgentCore is not executed. A Gateway target would be configured, from the public docs only,
as an MCP target pointing at `<ANERP_PUBLIC_URL>/mcp` with an outbound bearer credential holding
an agent token minted by `mint_token`; the harness would then talk to the Gateway endpoint the
way the other adapters talk to the loopback servers.
