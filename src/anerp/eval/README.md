# Evaluation harness

`anerp.eval` is the paper's data source (DESIGN.md §14): the agent-native tool surface
(**treatment**) against a naive CRUD MCP server over the same tables (**control**,
`crud_server.py`, the only code that bypasses the dispatcher), across three SDK adapters and
twenty tasks, three runs each.

## The comparison is clean by construction

Both arms run **in the harness process against one database**, so they differ in nothing but
the tool surface:

- one kernel database (`ANERP_EVAL_DATABASE_URL`, the Postgres from `docker-compose.yml`;
  SQLite in memory if unset), reset through the `reset_and_seed` tool before every run;
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
docker compose up -d --wait                            # Postgres 17 on 127.0.0.1:5432
export ANERP_EVAL_DATABASE_URL=postgresql+psycopg://anerp:anerp@127.0.0.1:5432/anerp_eval
export ANTHROPIC_API_KEY=… OPENAI_API_KEY=… GOOGLE_API_KEY=…   # only the adapters you run
```

The devcontainer does all of this except `docker compose up` (it has docker-in-docker and
exports `ANERP_EVAL_DATABASE_URL`). The compose credentials are throwaway and bound to loopback;
`.github/workflows/eval.yml` uses the same image and credentials as a service container.

## Running

```bash
uv run --all-extras anerp eval --clients scripted --servers treatment   # checker self-test, no LLM
uv run --all-extras anerp eval \
  --clients claude_agent_sdk,openai_agents_sdk,google_adk \
  --servers treatment,control --tasks all --runs 3 --run-id 2026-09-matrix
```

Outputs land in `results/<run_id>/`: `raw.jsonl` (one row per run with metrics and the full
tool-call trace), `summary.csv` and `report.md` (per server x client x task, the §14.4 metrics),
and `success.png` when matplotlib is installed. `--tasks p2p_01_simple --runs 1` is a cheap
probe (about $1 per adapter) before the full matrix. Runs on one kernel are sequential; budget
roughly 60-90 s per run.

Models are pinned per adapter and recorded with the run: `ANERP_ANTHROPIC_MODEL`
(`claude-opus-5`), `ANERP_OPENAI_MODEL` (`gpt-5`), `ANERP_GOOGLE_MODEL`
(`gemini-3.1-pro-preview`; `gemini-2.5-pro` is retired for new users).

If the database is down the harness stops before the first run with a message pointing here.

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
