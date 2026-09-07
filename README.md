# anerp — an agent-native headless ERP kernel

`anerp` is an ERP kernel with **no user interface**. Its only public surface is a set of typed
*business-operation tools* over the Model Context Protocol (MCP) and a task-level agent over the
Agent-to-Agent protocol (A2A). Every write tool runs in `simulate` (validate + project effects,
nothing persisted) or `commit` (persist, post to a double-entry ledger, emit a signed receipt and
an event). Finance (GL/AP/AR/periods), Procurement (procure-to-pay) and Sales (order-to-cash)
share one ledger.

It exists to test one thesis: *an ERP designed for agents from the ground up yields materially
higher agent task success and safety than a UI-era ERP with an MCP wrapper.* The design is in
[DESIGN.md](DESIGN.md); the trimmed architecture note is [ARCHITECTURE.md](ARCHITECTURE.md).

## The six rules

1. Tools are business operations, not CRUD (`create_purchase_order`, never `insert_row`).
2. Every write tool is two-phase: `mode="simulate"` then `mode="commit"`, same payload.
3. Every commit is idempotent (`idempotency_key`) and returns an Ed25519-signed receipt.
4. Rules live in a declarative policy layer (`policies/default.yaml`), evaluated identically in
   both modes.
5. Every state change emits an event (`poll_events`, `GET /events/stream`).
6. Compensation is first-class: every write tool names its reversing tool; nothing is deleted.

## Quickstart (Codespace or any cloud session)

```bash
uv sync                                   # Python 3.12, all deps
uv run pytest -q                          # 39 tests, SQLite in memory, no network
cp .env.example .env                      # local-to-the-codespace run only; never commit .env
uv run anerp seed                         # chart of accounts, periods, 2 suppliers, 2 customers, 4 items
uv run anerp token mint human:you --kind admin --scopes 'admin:*'   # prints the clear token once
uv run anerp serve                        # foreground; MCP at /mcp, A2A at /a2a, SSE at /events/stream (`anerp start` = migrate + serve)
```

Connect Claude Code to a running server (cloud or Codespace, forwarded port):

```bash
claude mcp add --transport http anerp https://<host>/mcp --header "Authorization: Bearer $ANERP_ADMIN_TOKEN"
```

The committed `.mcp.json` references `${ANERP_ADMIN_TOKEN}` and `${ANERP_URL}` from the
environment, so no token is ever in git. `anerp-local` in the same file runs the stdio transport
(`uv run anerp mcp --stdio`, token from `ANERP_TOKEN`). Verify with `/mcp` inside the session,
then try:

```
create_purchase_order  {supplier: "ACME", lines: [{sku: "WIDGET-1", qty: 10, unit_cost: "50.00"}]}          # simulate
create_purchase_order  {mode: "commit", idempotency_key: "demo-po-1", simulation_id: "...", ...}                # commit
receive_goods → post_supplier_invoice → pay_supplier → trace_document PO-000002 → get_trial_balance
```

## Tool surface (63 tools)

| Module | Tools |
|---|---|
| masterdata | `create_/deactivate_/activate_` supplier, customer, item, account |
| procurement | `create_purchase_order`, `approve_purchase_order`, `receive_goods`, `post_supplier_invoice` (three-way match), `pay_supplier`, `cancel_purchase_order`, `reverse_goods_receipt`, `reverse_supplier_invoice`, `reverse_supplier_payment` |
| sales | `create_sales_order` (credit check), `ship_order` (stock check, COGS), `issue_customer_invoice`, `record_customer_payment`, `issue_credit_note`, `cancel_sales_order`, `reverse_shipment`, `reverse_customer_payment` |
| finance | `post_journal_entry`, `reverse_journal_entry`, `close_period` (readiness checklist), `reopen_period` |
| approvals | `list_pending_approvals`, `request_approval`, `reject_approval` (+ `approve_purchase_order`; human tokens only) |
| query | `get_document`, `search_documents`, `list_open_items`, `get_account_balance`, `get_trial_balance`, `get_ledger_entries`, `get_inventory`, `get_period`, `poll_events`, `verify_receipt`, `describe_tool`, `list_capabilities` |
| troubleshoot | `trace_document`, `explain_balance`, `explain_error`, `replay_simulate`, `find_duplicates`, `get_reconciliation`, `get_agent_activity`, `get_request_log` |
| admin | `mint_token`, `revoke_token`, `list_tokens`, `update_policy`, `rotate_signing_key`, `reset_and_seed` (dev only), `get_system_status` |

Every write tool's description follows the same template (purpose, preconditions, effects on
commit, simulate-first, idempotency, compensating tool, common errors). Errors carry a stable
code (`VALIDATION_ERROR`, `NOT_FOUND`, `PRECONDITION_FAILED`, `POLICY_DENIED`,
`REQUIRES_APPROVAL`, `PERIOD_CLOSED`, `INSUFFICIENT_STOCK`, `MATCH_VARIANCE_EXCEEDED`,
`CREDIT_LIMIT_EXCEEDED`, `IDEMPOTENCY_CONFLICT`, `STALE_SIMULATION`, `UNAUTHORIZED`,
`FORBIDDEN`) plus `retry_advice`. Business errors are *returned* in simulate mode, never raised.

MCP extras: resources `anerp://chart-of-accounts`, `anerp://policies`, `anerp://capabilities`,
`anerp://events/latest`; prompts `procure_to_pay_playbook`, `order_to_cash_playbook`,
`period_close_checklist`.

## Protocol and vendor matrix

| Client | Transport | How it connects | Status |
|---|---|---|---|
| Claude Code (stdio) | MCP stdio | `.mcp.json` → `uv run anerp mcp --stdio` | tested in-process via the same tool surface |
| Claude Code / Claude Desktop (remote) | MCP streamable HTTP | `claude mcp add --transport http … --header Authorization` | HTTP transport covered by `tests/e2e/test_mcp_http.py` |
| Claude Agent SDK | MCP streamable HTTP | `anerp.eval.clients.claude_agent_sdk` | adapter written, needs `claude-agent-sdk` + `ANTHROPIC_API_KEY`; not run in CI |
| OpenAI Agents SDK | MCP streamable HTTP | `anerp.eval.clients.openai_agents_sdk` | adapter written, needs `openai-agents` + `OPENAI_API_KEY`; not run in CI |
| Google ADK | MCP streamable HTTP | `anerp.eval.clients.google_adk` | adapter written, needs `google-adk` + `GOOGLE_API_KEY`; not run in CI |
| Any A2A client | A2A JSON-RPC (v1.0) | `GET /.well-known/agent-card.json`, `POST /a2a` | covered by `tests/e2e/test_a2a.py` |
| AWS Bedrock AgentCore | MCP streamable HTTP (Gateway) | **not executed** — see below | described only |

**AWS AgentCore (description from public documentation only; nothing is run or hosted on AWS).**
Amazon Bedrock AgentCore Gateway can front an existing MCP server as a "target": you register the
anerp endpoint URL and the outbound authorization (an API-key/bearer credential stored in the
Gateway's credential provider), the Gateway then lists anerp's tools to AgentCore Runtime agents
and forwards `tools/call` with the configured `Authorization` header. Because anerp is stateless
over streamable HTTP and authenticates per request, the same `anerp_…` token an admin mints with
`mint_token` would be the outbound credential. This project does not include AWS code,
dependencies or infrastructure (conflict-of-interest boundary, DESIGN.md §16).

## Human in the loop

Purchase orders above the approval threshold (`po_approval_threshold`, 10,000.00 by default) are
persisted as `draft` with a pending `ApprovalRequest`. `approve_purchase_order` and
`reject_approval` refuse `kind=agent` tokens (`human_approval_only`) and the creator cannot
approve their own PO (`po_approver_differs`). The A2A agent returns `input-required` with the
request id; `list_pending_approvals` is the inbox for any head (chat client, CLI, console).

Tools that cannot hold a pending version return `REQUIRES_APPROVAL` instead. That path still
writes exactly one thing, receipted: a pending `ApprovalRequest` deduplicated on tool and
payload hash, so retries and duplicate submissions share it, and the idempotency record for the
key, so a replay returns the same answer. After approval the agent commits again with a new key.

## Admin bootstrap

1. Set `ANERP_BOOTSTRAP_ADMIN_TOKEN` (generate one with `uv run anerp token bootstrap`),
   `ANERP_TOKEN_PEPPER` and `ANERP_SIGNING_KEY_PEM` (`uv run anerp keygen`) on the host.
2. First start stores the token's hash as `admin:bootstrap` and logs a warning.
3. Call `mint_token` to create your personal `admin` token and one `agent` token per client SDK
   (scopes are a subset of the caller's; `admin:*` can only be minted by `admin:*`).
4. `revoke_token` on `admin:bootstrap`. Tokens are stored as `sha256(pepper + token)`, never clear.
5. `reset_and_seed("baseline")` on `dev` (refused unless `ANERP_ENV=dev`); check with
   `get_trial_balance` and `get_system_status`.

## Troubleshooting from any head

`trace_document PO-000124` shows the whole causal chain (PO → GRN → SINV → JE → PAY) with
receipts, actors, `on_behalf_of` and event sequence numbers. `explain_balance 1300 2026-09`
groups movements by source document and flags reversal pairs. `explain_error <request_id>`
returns the redacted envelope and the policy rules that fired. `replay_simulate <receipt_id>`
re-runs a past payload against current state and diffs the projection. CLI mirrors:
`anerp trace`, `anerp tb`, `anerp verify-receipt`, `anerp recon gr_ir|ap|ar|inventory`,
`anerp status` — thin clients of the same tools (in-process, or over HTTP with `ANERP_URL` and
`ANERP_TOKEN`).

## Evaluation harness

`anerp.eval` compares the agent-native surface (**treatment**) against a naive CRUD MCP server
over the same tables (**control**, `src/anerp/eval/crud_server.py`, the only code that bypasses
the dispatcher). Twenty tasks live in `src/anerp/eval/tasks/*.yaml` with goal-state assertions
and traps (approval threshold, price variance, credit limit, stock, closed period, retry storm,
recovery). Metrics per run: task success, unsafe write rate, simulate-before-commit rate,
duplicate document rate, recovery success, cost (tokens, tool calls, wall clock), trial-balance
integrity.

```bash
uv run anerp eval --clients scripted --servers treatment            # harness self-test, no LLM
LLM_PROVIDER=anthropic uv run anerp eval --clients in_process --runs 3   # same model, both servers
ANERP_URL=https://anerp-dev… ANERP_ADMIN_TOKEN=… uv run anerp eval --clients claude_agent_sdk,openai_agents_sdk
```

Outputs: `results/<run_id>/raw.jsonl`, `summary.csv`, `report.md` (and `success.png` when
matplotlib is installed). `eval.yml` runs the matrix from GitHub Actions against `dev`. The
`scripted` client is a deterministic oracle used to validate the checkers; it is not part of the
paper's matrix.

## Deployment (cloud-only, non-AWS)

Code lives in GitHub; the ERP runs on Railway with its Postgres plugin. `railway.json` builds
`deploy/Dockerfile` and starts the service with `anerp start`, which applies migrations and then
serves in the foreground in one process. Railway's `DATABASE_URL`, `PORT` and
`RAILWAY_PUBLIC_DOMAIN` are accepted when the `ANERP_*` variables are unset; a missing signing
key is generated on first start and kept in the `server_key` table. See
[deploy/README.md](deploy/README.md) for the variables, the bootstrap sequence and the restore
drill. Backups rely on the provider's snapshots; the `demo` database is never reset.

## Boundaries (DESIGN.md §16)

- **Conflict of interest**: no AWS code, dependencies, or hosting; no SAP/Oracle/Microsoft/Workday
  specific code. Vendors appear only in docs and in `a2a_agent/llm/` and `eval/clients/`.
- **Admin**: a scoped, receipted role; no unauthenticated routes, no direct SQL endpoints, no debug
  flags around `core.dispatch`.
- **Patent boundary (intentionally not implemented)**: delegation-chain/attenuated tokens between
  agents; segregation-of-duties conflict detection beyond the single `po_approver_differs`
  control; budget reservation or metering of agent spend; hash-chained/Merkle-anchored ledgers;
  compliance evidence packages. Receipts are independent records with no `prev_hash`.
- **Simplicity**: one dispatcher, one transaction per commit, no background workers, sync SQLAlchemy.

## Development

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
```

Tests run without network and without Postgres. `tests/property/` holds the hypothesis ledger
invariants (trial balance stays balanced under random entries; reversals mirror and never mutate
the original). Integration tests against a hosted database are marked `integration` and run only
in CI with `ANERP_DATABASE_URL` set.

## License and citation

Apache-2.0. See [CITATION.cff](CITATION.cff).
