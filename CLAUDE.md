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
| HTTP app (`/mcp`, `/api`, `/a2a`, `/events/stream`, `/healthz`, well-known) | `src/anerp/server.py` |
| HTTP facade (`POST /api/{query,simulate,commit}/{tool}`) | `src/anerp/facade.py` |
| CLI | `src/anerp/cli.py` |

## Conventions that are easy to miss

- Money: payloads take `Decimal` strings (`"50.00"`); storage and responses use integer cents.
- Numbers (`PO-000123`) are allocated inside the commit transaction; simulate shows
  `PO-000124 (projected)`.
- `Projection.on_requires_approval` lets a tool persist a pending version (PO `draft`) when policy
  says `requires_approval`; tools without it get `REQUIRES_APPROVAL` and only an `ApprovalRequest`
  is written.
- The request log and simulation store are in-process memory, so simulate is provably zero-write.
- `ctx.get`/`ctx.get_by_ref` record touched rows; their `state_version`s feed the receipt hashes and
  the `STALE_SIMULATION` check.
# keel-console — CLAUDE.md

Keel is a headless, agent-native ERP. This repo is a **head**: a thin, replaceable web console that talks to Keel only through its HTTP facade. The console exists to let humans see what agents did and to serve as the approval and goods-acceptance inbox. It proves a thesis from the research paper: because every fact in Keel is behind a tool, a UI can be built in an afternoon and thrown away.

## Non-negotiables

1. **No business logic here.** Every number, status, and decision comes from Keel. The console never computes totals, balances, variances, or due dates. If a screen needs a derived value, ask for a Keel tool that returns it.
2. **No privileged path.** The console uses exactly the same bearer tokens and scopes as agents. What a user can see or do is whatever their token allows; the UI hides or disables what the token cannot do, and Keel is the enforcer.
3. **Token stays in the browser.** The user pastes a Keel token once; it lives in `sessionStorage` only. Never in the repo, never in a build artifact, never in a URL, never logged.
4. **Read-mostly.** The only writes the console performs are the human decisions: `approve_purchase_order`, `reject_approval`, `accept_goods`, `reject_goods`. Each shows the projected effects from Keel first (simulate) and asks for confirmation before commit, with a fresh idempotency key per commit (`console:<request_id>:<tool>`).
5. **Keep vendor names out.** No AI-vendor SDKs, no cloud-provider SDKs. This is a static site that calls one API.

## How it talks to Keel

- Base URL from `VITE_KEEL_URL` at build time (default `https://headless-erp-production-0480.up.railway.app`), overridable by the user in Settings.
- `POST {base}/api/query/{tool}` for read tools, `POST {base}/api/simulate/{tool}` and `POST {base}/api/commit/{tool}` for writes. Body is the tool payload; commit bodies also carry `idempotency_key` and optional `simulation_id`. Header `Authorization: Bearer <token>`.
- Events: `GET {base}/events/stream?after_seq=N` (SSE) with the same header, falling back to polling `poll_events` every 5 s if SSE is unavailable.
- All responses have the Keel shape: `{ok, mode, request_id, ...}` or `{ok:false, error:{code, message, details}}`. Show `error.code` and `error.message` verbatim; show `request_id` on every error so it can be pasted into `explain_error`.

## Pages

| Route | Keel tools | Notes |
|---|---|---|
| `/` Status | `GET /healthz`, `get_system_status` | env badge, migration head, key id, event seq, policy version, token subject and scopes |
| `/events` | SSE stream, `poll_events` | live feed, filter by type and document, click → trace |
| `/ledger` | `get_trial_balance`, `get_account_balance`, `explain_balance`, `get_ledger_entries` | period selector; account row expands into movements by source document |
| `/open-items` | `list_open_items` | AP and AR tabs; overdue highlighted; link to invoice trace |
| `/inventory` | `get_inventory`, `get_reconciliation(inventory)` | on-hand, standard cost, GL vs subledger difference |
| `/approvals` | `list_pending_approvals`, `approve_purchase_order`, `reject_approval`, `accept_goods`, `reject_goods` | the human inbox; goods acceptance shows expected quantities from the request and editable accepted/damaged counts per line |
| `/trace` | `trace_document`, `search_documents`, `get_document` | search box for a document number; render the chain as a vertical timeline with receipts and events inline |
| `/receipts` | `verify_receipt`, `get_request_log`, `explain_error` | paste a receipt id or request id |
| `/recon` | `get_reconciliation` for gr_ir, ap, ar, inventory; `get_period` | close-readiness checklist as read-only; no close button (Controller agent's job) |
| `/settings` | — | base URL, token entry (masked), clear session |

## Stack and conventions

- Vite + React + TypeScript, single-page, client-side routing. Plain CSS or a small utility layer; no heavy component library.
- One `keelClient.ts` module wraps every call; components never call `fetch` directly.
- Money arrives from Keel as strings or minor units; format for display only, never do arithmetic.
- Every list is paged the way Keel pages (`limit`, `cursor`); no client-side "load everything."
- Tests: a mocked `keelClient` with recorded Keel responses; component tests for approvals (simulate → confirm → commit) and goods acceptance (per-line counts).
- Deploy as a static site (Railway static service or GitHub Pages). No server component in this repo.

## Build order

1. `keelClient.ts` + Settings page + Status page. Verify against live Keel with a read-only token.
2. Events + Trace. These are the demo pages.
3. Ledger, Open Items, Inventory, Recon.
4. Approvals (the only write pages), with simulate-then-commit and idempotency keys.
5. Receipts/explain_error, polish, deploy.

Stop and ask if any page seems to need logic that Keel does not expose; the answer is a new Keel query tool, not console code.
