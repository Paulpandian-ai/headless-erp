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
uv run pytest -q                          # 67 tests, SQLite in memory, no network
cp .env.example .env                      # local-to-the-codespace run only; never commit .env
uv run anerp seed                         # chart of accounts, periods (2026-08 closed), ACME/BOLT, NORTH/HARB, 4 items with opening stock
uv run anerp token mint human:you --kind admin --scopes 'admin:*'   # prints the clear token once
uv run anerp serve                        # foreground; MCP at /mcp, HTTP facade at /api, A2A at /a2a, SSE at /events/stream (`anerp start` = migrate + serve)
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
create_purchase_order  {supplier: "ACME", lines: [{sku: "VALVE-2IN", qty: 10, unit_cost: "50.00"}]}         # simulate
create_purchase_order  {mode: "commit", idempotency_key: "demo-po-1", simulation_id: "...", ...}                # commit
receive_goods (agent: parks a goods-acceptance request) → accept_goods (human token) → post_supplier_invoice
→ pay_supplier → trace_document PO-000002 → get_trial_balance
```

## Tool surface (65 tools)

| Module | Tools |
|---|---|
| masterdata | `create_/deactivate_/activate_` supplier, customer, item, account |
| procurement | `create_purchase_order`, `approve_purchase_order`, `receive_goods` (humans post; agents park a goods-acceptance request), `accept_goods`, `reject_goods`, `post_supplier_invoice` (three-way match on accepted quantities), `pay_supplier`, `cancel_purchase_order`, `reverse_goods_receipt`, `reverse_supplier_invoice`, `reverse_supplier_payment` |
| sales | `create_sales_order` (credit check), `ship_order` (stock check, COGS), `issue_customer_invoice`, `record_customer_payment`, `issue_credit_note`, `cancel_sales_order`, `reverse_shipment`, `reverse_customer_payment` |
| finance | `post_journal_entry`, `reverse_journal_entry`, `close_period` (readiness checklist), `reopen_period` |
| approvals | `list_pending_approvals` (kinds `po_approval`, `goods_acceptance`, `invoice_variance`), `request_approval`, `reject_approval` (+ `approve_purchase_order`, `accept_goods`, `reject_goods`; human tokens only) |
| query | `get_document`, `search_documents`, `list_document_types`, `list_open_items`, `get_account_balance`, `get_trial_balance`, `get_ledger_entries`, `get_inventory`, `get_period`, `get_current_period`, `poll_events`, `verify_receipt`, `describe_tool`, `list_capabilities`, `whoami` |
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

## HTTP facade

For callers that speak plain HTTP rather than MCP (a browser console, `curl`, a scripted client),
the same tool surface is exposed at three routes:

```
POST /api/query/{tool}      -> core.run_query
POST /api/simulate/{tool}   -> core.dispatch, mode=simulate
POST /api/commit/{tool}     -> core.dispatch, mode=commit
```

The body is the tool payload; on simulate and commit the envelope fields `idempotency_key`,
`simulation_id` and `on_behalf_of` sit alongside it, exactly as in MCP `tools/call` arguments. Same
bearer tokens, same scopes, same response JSON -- the facade holds no business logic of its own, so
anything true of the MCP surface is true here.

```bash
curl -sX POST "$ANERP_URL/api/query/get_trial_balance" \
  -H "Authorization: Bearer $ANERP_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"period_code":"2026-09"}'

curl -sX POST "$ANERP_URL/api/simulate/create_purchase_order" \
  -H "Authorization: Bearer $ANERP_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"supplier":"ACME","lines":[{"sku":"WIDGET-1","qty":10,"unit_cost":"50.00"}]}'
```

HTTP status is 200 for anything the kernel answered, including business errors -- read `ok` and
`error.code` from the body, as an MCP client would. Only a request that fails to authenticate gets
a 401; a token that authenticates but lacks the tool's scope gets `FORBIDDEN` in the body (the SSE
route `/events/stream` is the exception and answers 403, since an event-source client only sees
the status). `POST /api/query/whoami` needs no scope and returns what the token is and which tools
it may call. Every tool's parameter names are the first line of its description
(`create_purchase_order(supplier, lines, memo?)`, `?` marking optional), and a `VALIDATION_ERROR`
repeats them under `error.details.expected_fields` / `required_fields`.

The routes are in the OpenAPI schema at `GET /openapi.json`. Browser origins come from
`ANERP_CORS_ORIGINS` (comma separated); unset means `*` in dev and test and no CORS headers at all
in demo and prod, where the origin has to be named.

## Protocol and vendor matrix

| Client | Transport | How it connects | Status |
|---|---|---|---|
| Claude Code (stdio) | MCP stdio | `.mcp.json` → `uv run anerp mcp --stdio` | tested in-process via the same tool surface |
| Claude Code / Claude Desktop (remote) | MCP streamable HTTP | `claude mcp add --transport http … --header Authorization` | HTTP transport covered by `tests/e2e/test_mcp_http.py` |
| Claude Agent SDK | MCP streamable HTTP | `anerp.eval.clients.claude_agent_sdk` | adapter written, needs `claude-agent-sdk` + `ANTHROPIC_API_KEY`; not run in CI |
| OpenAI Agents SDK | MCP streamable HTTP | `anerp.eval.clients.openai_agents_sdk` | adapter written, needs `openai-agents` + `OPENAI_API_KEY`; not run in CI |
| Google ADK | MCP streamable HTTP | `anerp.eval.clients.google_adk` | adapter written, needs `google-adk` + `GOOGLE_API_KEY`; not run in CI |
| Any A2A client | A2A JSON-RPC (v1.0) | `GET /.well-known/agent-card.json`, `POST /a2a` | covered by `tests/e2e/test_a2a.py` |
| Browser console / `curl` / any HTTP client | HTTP facade | `POST /api/{query,simulate,commit}/{tool}` | covered by `tests/e2e/test_http_facade.py` |
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

Three decisions are structurally human; the kernel does not care which head delivers them (chat
client, CLI, console), only that the tool is called with a human token (`human_approval_only`).

| Kind | Raised when | Human tools |
|---|---|---|
| `po_approval` | a purchase order exceeds the threshold (10,000.00 by default): the PO is persisted as `draft` | `approve_purchase_order` (not the creator: `po_approver_differs`), `reject_approval` |
| `goods_acceptance` | an agent commits `receive_goods`: nothing is posted, the projection is parked | `accept_goods` posts the receipt at the counted quantities (short, damaged, over-shipped lines recorded); `reject_goods` |
| `invoice_variance` | `post_supplier_invoice` fails the three-way match against accepted quantities | correct and re-post, or `reject_approval` |

Agents may simulate every one of these operations and see the decision in `policy`. Parked
requests are deduplicated on tool and payload hash, receipted, and idempotent, so retries share
one request. The A2A agent returns `input-required` with the request id and resumes after the
human acts; `list_pending_approvals` (filter by `kind`) is the inbox.

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
recovery). Tasks that need a warehouse count declare `human_loop`; the harness plays the human
between agent rounds (accepting at the expected quantities unless the task overrides a count). Metrics per run: task success, unsafe write rate, simulate-before-commit rate,
duplicate document rate, recovery success, cost (tokens, tool calls, wall clock), trial-balance
integrity.

Both arms run against **one local kernel in the harness process** (the Postgres from
`docker-compose.yml`), each tool surface served on a loopback port for the SDK adapters, so
treatment and control differ in nothing but the tool surface. Setup, running, models and the
google-adk interpreter are documented in [`src/anerp/eval/README.md`](src/anerp/eval/README.md).

```bash
docker compose up -d --wait
export ANERP_EVAL_DATABASE_URL=postgresql+psycopg://anerp:anerp@127.0.0.1:5432/anerp_eval
uv run --all-extras anerp eval --clients scripted --servers treatment            # self-test, no LLM
uv run --all-extras anerp eval --clients claude_agent_sdk,openai_agents_sdk,google_adk --runs 3
```

Outputs: `results/<run_id>/raw.jsonl`, `summary.csv`, `report.md` (and `success.png` when
matplotlib is installed). `eval.yml` runs the matrix from GitHub Actions against a Postgres
service. The `scripted` client is a deterministic oracle used to validate the checkers; it is
not part of the paper's matrix.

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
