# Instructions for Claude Code (from DESIGN.md §19)

- Read DESIGN.md fully before the first edit; treat §2.1, §6, §8.1, §16 and §20 as invariants.
- Work phase by phase (§15). Before starting a phase, restate its definition of done; after
  finishing, run `uv run ruff check . && uv run mypy src && uv run pytest -q` and commit with
  message `phase-N: <summary>`. Push to a branch and open a PR per phase; `main` deploys to Railway.
- Never write a secret to a tracked file. Secrets come from the environment only (§13). If a value
  looks like a token or key, stop.
- Tests must run without network and without Postgres (SQLite in-memory fixture in
  `tests/conftest.py`); integration tests that need the hosted database are marked
  `@pytest.mark.integration` and run only in CI with `ANERP_DATABASE_URL` set.
- Never add a second write path around `core.dispatch`. Never write to the DB in simulate mode.
  Never delete rows. The only exception is `anerp/eval/crud_server.py`, the ablation baseline,
  which is marked `# BASELINE ONLY`.
- Every new write tool needs: Pydantic payload, projection function, policy facts, simulate test,
  commit test, replay test, compensating-tool test, and a description following §7.6 (fill the
  `purpose`, `preconditions`, `effects`, `compensating_tool`, `common_errors` class attributes;
  `WriteTool.description()` renders the template).
- Keep vendor names out of `src/anerp/core`, `ledger`, `policy`, `events`, and the module packages.
  Vendor-specific code lives only under `a2a_agent/llm/` and `eval/clients/`.
- If a requirement seems to need anything listed under the patent boundary in §16, stop and ask
  instead of implementing.
- Prefer small, reviewable commits. Do not refactor across modules without stating why.

## Where things are

| Concern | Path |
|---|---|
| Dispatcher, envelope, errors, projection, registry | `src/anerp/core/` |
| Posting, sequences, receipts/keys, idempotency, trial balance | `src/anerp/ledger/` |
| Policy engine (safe evaluator) and default rules | `src/anerp/policy/`, `policies/default.yaml` |
| Tools per module | `src/anerp/{masterdata,procurement,sales,finance,approvals,troubleshoot,admin}/tools.py` |
| Query tools | `src/anerp/finance/query_tools.py` |
| MCP server (HTTP + stdio), auth, resources, prompts | `src/anerp/mcp_server/` |
| A2A agent (card, executor, skills, LLM loop) | `src/anerp/a2a_agent/` |
| Eval harness (control server, tasks, clients, metrics, report) | `src/anerp/eval/` |
| HTTP app (`/mcp`, `/a2a`, `/events/stream`, `/healthz`, well-known) | `src/anerp/server.py` |
| CLI | `src/anerp/cli.py` |

## Conventions that are easy to miss

- Money: payloads take `Decimal` strings (`"50.00"`); storage and responses use integer cents.
- Numbers (`PO-000123`) are allocated by `ctx.number_for` during projection in commit mode (inside
  the transaction, rolled back on failure); simulate shows `PO-000124 (projected)`. Never copy a
  number into another column or string before that: Postgres enforces `VARCHAR(16)`.
- `dispatch(..., session=s)` runs a commit inside the caller's transaction (no commit, no rollback,
  no after_commit hooks); the seed uses it so `anerp seed` and `reset_and_seed` are atomic.
- `Projection.on_requires_approval` lets a tool persist a pending version (PO `draft`) when policy
  says `requires_approval`; tools without it get `REQUIRES_APPROVAL` and only an `ApprovalRequest`
  (of the tool's `approval_kind`, pointing at `Projection.approval_target`) is written. A tool's
  `park_on_deny` maps policy error codes to a kind parked while the error is still returned.
- Goods receipts are posted by humans: `receive_goods` under an agent token parks a
  `goods_acceptance` request; `accept_goods` / `reject_goods` resolve it (scope
  `procurement:receive`, `human_approval_only`). Three-way match uses accepted quantities.
- Baseline seed (DESIGN.md Amendment A): ACME/BOLT, NORTH/HARB, PUMP-SM/VALVE-2IN/HOSE-10M/FLANGE-4
  with on-hand 0/5/40/100 as opening entries (`create_item` `opening_qty`), period 2026-08 closed,
  no purchase order or GR/IR balance.
- The request log and simulation store are in-process memory, so simulate is provably zero-write.
- `ctx.get`/`ctx.get_by_ref` record touched rows; their `state_version`s feed the receipt hashes and
  the `STALE_SIMULATION` check.
