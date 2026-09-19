# Resilience experiments

Three experiments on the same kernel (DESIGN.md §14), run 2026-09-16. Deterministic ones run on SQLite in memory and on PostgreSQL 17 (`sqlite.json` / `postgres.json`); the agent experiment ran in the Codespace against PostgreSQL 17 with each vendor's mid-tier model through its own agent SDK, the harness's loopback MCP server injecting the fault.

## 3. Commit failure / event-state divergence (deterministic)

A failure is injected at every distinct stage of the commit transaction, for four write tools with different effect mixes (`post_journal_entry`: journal only; `create_purchase_order`: documents + lines + events, no journal; `ship_order`: inventory + journal; `post_supplier_invoice`: open item + journal + PO line updates). After each injected failure: no document, journal entry or line, open item, receipt, event or idempotency record may remain; the trial balance must balance; a retry with the same idempotency key must be `applied` (a failed commit must not leave a record that would make the retry a false replay); a second retry must be `replayed`.

| stage (fails after ...) | what has been written when it fails |
|---|---|
| documents | documents, open items and inventory deltas flushed |
| journal | the journal entry and its lines posted |
| events | the first event emitted |
| receipt | the receipt signed and flushed |
| idempotency | the idempotency record stored |
| db_commit | everything flushed; the database refuses COMMIT (OperationalError) |

| backend | trials (tool x stage) | n/a (stage not reached) | all-or-nothing | TB balanced after | retry same key applied | second retry replayed |
|---|---|---|---|---|---|---|
| sqlite | 24 | 1 | 23/23 | 23/23 | 23/23 | 23/23 |
| postgres 127.0.0.1:5432/anerp_eval | 24 | 1 | 23/23 | 23/23 | 23/23 | 23/23 |

The dispatcher turns the injected exception into an `INTERNAL_ERROR` envelope (the client is told the commit failed) and the owned transaction rolls back; nothing of the failed commit is visible afterwards. The one n/a cell is `create_purchase_order` at the journal stage: it posts no journal, so that stage does not exist for it.

## 2. Concurrency / stale writes (deterministic, scripted contention)

Actor A prepares a write from what it saw; actor B changes the world; A writes. Treatment: A simulates, B commits, A commits against its `simulation_id` (and, in a separate trial, without ever simulating). Control: A reads rows, B mutates rows, A writes rows from its stale read; nothing on that surface can refuse it, so the resulting posting is checked by hand and by the harness's post-hoc checker.

**sqlite**

| scenario | treatment: commit with simulation | re-simulate says | commit without simulation | control: posting correct? | control detail | post-hoc checker |
|---|---|---|---|---|---|---|
| stock_consumed | STALE_SIMULATION | INSUFFICIENT_STOCK | INSUFFICIENT_STOCK | NO | 8 units shipped against 5 on hand; item row shows 0 (true: -3) | nothing flagged |
| period_closed | STALE_SIMULATION | PERIOD_CLOSED | PERIOD_CLOSED | NO | 1 entry posted into closed period 2026-08 | nothing flagged |
| po_already_invoiced | STALE_SIMULATION | MATCH_VARIANCE_EXCEEDED | MATCH_VARIANCE_EXCEEDED | NO | 8 units invoiced against 4 received; PO line shows invoiced_qty 4; GR/IR 1400 net 20000 cents | nothing flagged |
| credit_limit_consumed | CREDIT_LIMIT_EXCEEDED | CREDIT_LIMIT_EXCEEDED | CREDIT_LIMIT_EXCEEDED | NO | open AR 160000 + open orders 400000 = 560000 cents against limit 500000 | nothing flagged |

**postgres**

| scenario | treatment: commit with simulation | re-simulate says | commit without simulation | control: posting correct? | control detail | post-hoc checker |
|---|---|---|---|---|---|---|
| stock_consumed | STALE_SIMULATION | INSUFFICIENT_STOCK | INSUFFICIENT_STOCK | NO | 8 units shipped against 5 on hand; item row shows 0 (true: -3) | nothing flagged |
| period_closed | STALE_SIMULATION | PERIOD_CLOSED | PERIOD_CLOSED | NO | 1 entry posted into closed period 2026-08 | nothing flagged |
| po_already_invoiced | STALE_SIMULATION | MATCH_VARIANCE_EXCEEDED | MATCH_VARIANCE_EXCEEDED | NO | 8 units invoiced against 4 received; PO line shows invoiced_qty 4; GR/IR 1400 net 20000 cents | nothing flagged |
| credit_limit_consumed | CREDIT_LIMIT_EXCEEDED | CREDIT_LIMIT_EXCEEDED | CREDIT_LIMIT_EXCEEDED | NO | open AR 160000 + open orders 400000 = 560000 cents against limit 500000 | nothing flagged |

Three of the four stale commits are refused as `STALE_SIMULATION` because a row the simulation touched (item, fiscal period, PO line) changed version; the fourth (credit limit) is not stale in that sense - the customer row never changed, the exposure did - and is refused by the credit rule re-evaluated at commit (`CREDIT_LIMIT_EXCEEDED`). An agent that skipped simulate is refused the same way. On the control surface all four postings go through and all four books are wrong; the post-hoc checker (negative stock, over-invoiced lines, over-threshold POs, unbalanced entries) flags none of them, because a stale write overwrites the very rows the checker reads - the item shows 0 on hand while 8 of 5 were shipped, the PO line shows 4 invoiced while 8 were billed.

A two-agent version (two LLM agents contending live) was not run; the deterministic result already shows the mechanism, and the agent-level question - how agents react to `STALE_SIMULATION` - is future work.

## 1. Induced timeout / duplicates (agents in the loop)

Once per run, the first write commit the kernel applies has its response replaced at the MCP server by a transport-timeout error (`TIMEOUT`, "no response was received ... may or may not have been applied"). The kernel holds the document, receipt, event and idempotency record; the agent, in the same session, still holds the key it chose. Five tasks (gl_01_manual_je, p2p_05_cancel, o2c_01_simple, o2c_04_credit_note, p2p_09_partial_payment) x 3 runs per vendor.

| behaviour | meaning |
|---|---|
| reused_key | retried the commit with the same idempotency key -> kernel `replayed`, one document |
| new_key_duplicate | retried with a fresh key -> kernel `applied` again, two documents |
| new_key_rejected | retried with a fresh key and the kernel refused it for a business reason |
| verified_no_retry | did not retry; queried (search/get_document/request log) and carried on with the document that exists |
| gave_up | neither retried nor looked |

| client | runs | reused_key | new_key_duplicate | new_key_rejected | verified_no_retry | gave_up | not_injected | duplicate docs | task success |
|---|---|---|---|---|---|---|---|---|---|
| claude_agent_sdk (claude-sonnet-5) | 15 | 1 | 0 | 0 | 14 | 0 | 0 | 0 | 15/15 |
| google_adk (gemini-3.8-flash) | 14 | 0 | 0 | 0 | 13 | 0 | 1 | 0 | 13/14 |
| openai_agents_sdk (gpt-5.6-terra) | 15 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 15/15 |

Per task:

| client | task | run 1 | run 2 | run 3 |
|---|---|---|---|---|
| claude_agent_sdk | gl_01_manual_je | verified_no_retry | verified_no_retry | reused_key |
| claude_agent_sdk | o2c_01_simple | verified_no_retry | verified_no_retry | verified_no_retry |
| claude_agent_sdk | o2c_04_credit_note | verified_no_retry | verified_no_retry | verified_no_retry |
| claude_agent_sdk | p2p_05_cancel | verified_no_retry | verified_no_retry | verified_no_retry |
| claude_agent_sdk | p2p_09_partial_payment | verified_no_retry | verified_no_retry | verified_no_retry |
| google_adk | gl_01_manual_je | verified_no_retry | verified_no_retry | verified_no_retry |
| google_adk | o2c_01_simple | verified_no_retry | verified_no_retry | verified_no_retry |
| google_adk | o2c_04_credit_note | verified_no_retry | verified_no_retry | not_injected |
| google_adk | p2p_05_cancel | verified_no_retry | verified_no_retry | verified_no_retry |
| google_adk | p2p_09_partial_payment | verified_no_retry | verified_no_retry | - |
| openai_agents_sdk | gl_01_manual_je | verified_no_retry | verified_no_retry | verified_no_retry |
| openai_agents_sdk | o2c_01_simple | verified_no_retry | verified_no_retry | verified_no_retry |
| openai_agents_sdk | o2c_04_credit_note | verified_no_retry | verified_no_retry | verified_no_retry |
| openai_agents_sdk | p2p_05_cancel | verified_no_retry | verified_no_retry | verified_no_retry |
| openai_agents_sdk | p2p_09_partial_payment | verified_no_retry | verified_no_retry | verified_no_retry |

**Contrast with dup_01_retry_storm.** There the retry came from a fresh session with no memory of the key and 8 of 9 runs created a second PO - every retry minted a new key (results/dup01-keys). Here, within the session, 0 of 44 runs produced a duplicate and 43 handled the timeout without one - one by replaying the same key (kernel `replayed`), the rest by looking (`search_documents`, `get_document`, `trace_document`) and continuing with the document that exists. The idempotency gap is a cross-session limitation: an agent that still holds its key uses it or checks; an agent that has forgotten it cannot, and the kernel cannot tell a repeated intent from a new one (DESIGN.md §8.2). The runs are 44 of the planned 45: the Codespace restarted during google_adk's last run (p2p_09 run 3) and the re-run was refused by Google with `403 PERMISSION_DENIED: Your project has been denied access`; Google's one `not_injected` row is a 503 before its first call.

