# Architecture (trimmed from DESIGN.md)

```
External agents (Claude Code / Agent SDK, OpenAI Agents SDK, Google ADK; A2A peers)
        │ MCP streamable HTTP or stdio          │ A2A JSON-RPC v1.0
┌───────▼───────────────────────┐   ┌───────────▼─────────────────────┐
│ anerp.mcp_server              │   │ anerp.a2a_agent                 │
│ tools/list, tools/call        │   │ Agent Card + finance agent      │
│ bearer auth + scopes          │   │ (same tool surface, in-process) │
└───────┬───────────────────────┘   └───────────┬─────────────────────┘
        └──────────────┬──────────────────────────┘
┌──────────────────────▼───────────────────────────────────────────────┐
│ anerp.core.dispatch  envelope → validate → project → policy →        │
│                      simulate: return projection | commit: apply     │
├──────────────┬──────────────┬──────────────┬────────────────────────┤
│ finance      │ procurement  │ sales        │ masterdata / approvals │
├──────────────┴──────────────┴──────────────┴────────────────────────┤
│ anerp.ledger  double-entry GL, sequences, idempotency, signed receipts│
│ anerp.policy  YAML rules, safe expression evaluator, both modes      │
│ anerp.events  append-only log, poll + SSE                            │
│ anerp.db      SQLModel; Postgres in deployments, SQLite in tests     │
└──────────────────────────────────────────────────────────────────────┘
│ anerp.eval    task suite, goal checkers, client adapters, CRUD control│
└──────────────────────────────────────────────────────────────────────┘
```

## One write path

`anerp.core.dispatch.dispatch(envelope, principal=None)` is the only way state changes: MCP,
A2A, the CLI, the seed script and the tests all go through it. A tool is a class with a Pydantic
payload and a `project(ctx, payload) -> Projection`. The projection is a pure description of the
effects: documents to create or update (with the exact field changes), one optional balanced
journal entry, open-item changes, inventory deltas, events, warnings, policy facts and the
compensating tool.

Pipeline (identical for both modes until the branch):

1. Parse the envelope and payload (`VALIDATION_ERROR`).
2. `project()` loads documents through the context (every loaded row is "touched") and checks
   preconditions (`NOT_FOUND`, `PRECONDITION_FAILED`).
3. The policy engine evaluates the projection's facts (`allow | deny | requires_approval`,
   plus warnings).
4. **simulate**: return validation, policy, projected effects, `state_versions`, a
   `simulation_id`; roll the session back. Nothing is written, not even a log row (the request
   log is in memory).
5. **commit**: idempotency lookup (replay or `IDEMPOTENCY_CONFLICT`), `STALE_SIMULATION` check
   against the recorded state versions, policy enforcement, then one transaction: allocate
   numbers, apply document changes (bumping `state_version`), apply inventory deltas, post the
   journal entry, create the approval request if pending, emit events, sign the receipt over
   (before_hash, action_hash, after_hash), store the idempotency record, commit.

Two edge cases in the commit branch are handled explicitly. A tool without a pending-version
hook that policy marks `requires_approval` writes only a deduplicated, receipted
`ApprovalRequest` plus the idempotency record, and returns `REQUIRES_APPROVAL`. Two concurrent
commits with the same key can both pass the lookup; the loser's idempotency insert fails at
commit time and the dispatcher answers with the winner's stored response (`status: replayed`).
Outside `ANERP_ENV=test` every call must carry a principal, from a token or an explicit
`local_principal()`; the envelope's self-declared actor is never trusted on its own.

## Ledger invariants

Only `ledger.posting.post_journal` writes journal rows. It refuses unbalanced entries, entries
with fewer than two lines, inactive accounts and closed periods. Balances are always computed
from lines. Reversals create a mirror entry with `reversal_of_id`; originals are never edited.
Hypothesis tests generate random balanced entries and check the trial balance after each one.

## Receipts and keys

`Receipt` rows are independent (no chaining). `signature` is Ed25519 over the canonical JSON of
`{tool_name, document_id, before_hash, action_hash, after_hash, signed_at}`. Public keys are
served at `/.well-known/anerp-keys.json`; `verify_receipt` recomputes the action hash from the
stored payload and checks the signature with the key id on the receipt, so rotated keys still
verify old receipts.

## Policy

`policies/default.yaml` holds rules with `applies_to` (tool names, `@groups`, `*`), an `effect`
(`deny` with optional `error_code`, `requires_approval`, `warn`) and a `condition` in a small
expression language (comparisons, boolean logic, arithmetic, attribute/index access,
comprehensions, a whitelist of functions). Unknown names never fire a rule. `update_policy`
validates and hot-swaps the engine; versions are kept in `policy_version`.

## Auth

Bearer tokens are looked up by `sha256(pepper + token)`; scopes are matched with module and
action wildcards (`procurement:*`, `*:read`, `admin:*`). The MCP transport is stateless; every
request carries its token. The stdio transport takes its token from the environment. OAuth
discovery is off by default because clients that see it may abandon a configured bearer header.

## Human in the loop

`ApprovalRequest.kind` names the decision. `create_purchase_order` above the threshold persists a
`draft` PO and a `po_approval` request. An agent commit of `receive_goods` posts nothing and parks
a `goods_acceptance` request holding the projection and payload; `accept_goods` (human) posts the
receipt at the counted quantities and `reject_goods` closes it. A refused `post_supplier_invoice`
parks an `invoice_variance` request while still returning `MATCH_VARIANCE_EXCEEDED`. Approval
tools reject agent tokens and self-approval. The A2A agent returns `input-required` with the
request id and resumes when the task receives another message after the human acts.
