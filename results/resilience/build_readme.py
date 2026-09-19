"""Assemble results/resilience/README.md from the three experiments' output files."""
import json
from collections import Counter
from pathlib import Path

R = Path("results/resilience")
out = ["# Resilience experiments\n",
       "Three experiments on the same kernel (DESIGN.md §14), run 2026-09-16. Deterministic ones run on SQLite in memory and on PostgreSQL 17 (`sqlite.json` / `postgres.json`); the agent experiment ran in the Codespace against PostgreSQL 17 with each vendor's mid-tier model through its own agent SDK, the harness's loopback MCP server injecting the fault.\n"]

# ---------------------------------------------------------------- 3
out.append("## 3. Commit failure / event-state divergence (deterministic)\n")
out.append("A failure is injected at every distinct stage of the commit transaction, for four write tools with different effect mixes (`post_journal_entry`: journal only; `create_purchase_order`: documents + lines + events, no journal; `ship_order`: inventory + journal; `post_supplier_invoice`: open item + journal + PO line updates). After each injected failure: no document, journal entry or line, open item, receipt, event or idempotency record may remain; the trial balance must balance; a retry with the same idempotency key must be `applied` (a failed commit must not leave a record that would make the retry a false replay); a second retry must be `replayed`.\n")
out.append("| stage (fails after ...) | what has been written when it fails |\n|---|---|\n| documents | documents, open items and inventory deltas flushed |\n| journal | the journal entry and its lines posted |\n| events | the first event emitted |\n| receipt | the receipt signed and flushed |\n| idempotency | the idempotency record stored |\n| db_commit | everything flushed; the database refuses COMMIT (OperationalError) |\n")
out.append("| backend | trials (tool x stage) | n/a (stage not reached) | all-or-nothing | TB balanced after | retry same key applied | second retry replayed |\n|---|---|---|---|---|---|---|")
for name in ("sqlite", "postgres"):
    p = R / "commit_failure" / f"{name}.json"
    if not p.exists(): continue
    d = json.loads(p.read_text()); ts = d["trials"]; ap = [t for t in ts if t["applicable"]]
    out.append(f"| {ap[0]['backend']} | {len(ts)} | {len(ts)-len(ap)} | {sum(t['all_or_nothing'] for t in ap)}/{len(ap)} | {sum(t['tb_balanced_after'] for t in ap)}/{len(ap)} | {sum(t['retry_same_key']=='applied' for t in ap)}/{len(ap)} | {sum(t['second_retry']=='replayed' for t in ap)}/{len(ap)} |")
out.append("\nThe dispatcher turns the injected exception into an `INTERNAL_ERROR` envelope (the client is told the commit failed) and the owned transaction rolls back; nothing of the failed commit is visible afterwards. The one n/a cell is `create_purchase_order` at the journal stage: it posts no journal, so that stage does not exist for it.\n")

# ---------------------------------------------------------------- 2
out.append("## 2. Concurrency / stale writes (deterministic, scripted contention)\n")
out.append("Actor A prepares a write from what it saw; actor B changes the world; A writes. Treatment: A simulates, B commits, A commits against its `simulation_id` (and, in a separate trial, without ever simulating). Control: A reads rows, B mutates rows, A writes rows from its stale read; nothing on that surface can refuse it, so the resulting posting is checked by hand and by the harness's post-hoc checker.\n")
for name in ("sqlite", "postgres"):
    p = R / "stale_writes" / f"{name}.json"
    if not p.exists(): continue
    d = json.loads(p.read_text())
    out.append(f"**{name}**\n\n" + d["summary_md"] + "\n")
out.append("Three of the four stale commits are refused as `STALE_SIMULATION` because a row the simulation touched (item, fiscal period, PO line) changed version; the fourth (credit limit) is not stale in that sense - the customer row never changed, the exposure did - and is refused by the credit rule re-evaluated at commit (`CREDIT_LIMIT_EXCEEDED`). An agent that skipped simulate is refused the same way. On the control surface all four postings go through and all four books are wrong; the post-hoc checker (negative stock, over-invoiced lines, over-threshold POs, unbalanced entries) flags none of them, because a stale write overwrites the very rows the checker reads - the item shows 0 on hand while 8 of 5 were shipped, the PO line shows 4 invoiced while 8 were billed.\n")
out.append("A two-agent version (two LLM agents contending live) was not run; the deterministic result already shows the mechanism, and the agent-level question - how agents react to `STALE_SIMULATION` - is future work.\n")

# ---------------------------------------------------------------- 1
out.append("## 1. Induced timeout / duplicates (agents in the loop)\n")
out.append("Once per run, the first write commit the kernel applies has its response replaced at the MCP server by a transport-timeout error (`TIMEOUT`, \"no response was received ... may or may not have been applied\"). The kernel holds the document, receipt, event and idempotency record; the agent, in the same session, still holds the key it chose. Five tasks (gl_01_manual_je, p2p_05_cancel, o2c_01_simple, o2c_04_credit_note, p2p_09_partial_payment) x 3 runs per vendor.\n")
out.append("| behaviour | meaning |\n|---|---|\n| reused_key | retried the commit with the same idempotency key -> kernel `replayed`, one document |\n| new_key_duplicate | retried with a fresh key -> kernel `applied` again, two documents |\n| new_key_rejected | retried with a fresh key and the kernel refused it for a business reason |\n| verified_no_retry | did not retry; queried (search/get_document/request log) and carried on with the document that exists |\n| gave_up | neither retried nor looked |\n")
raw = R / "timeout_duplicates" / "raw.jsonl"
if raw.exists():
    from anerp.eval.resilience.timeout_duplicates import summarize
    out.append(summarize(raw) + "\n")
    rows = [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
    out.append("Per task:\n\n| client | task | run 1 | run 2 | run 3 |\n|---|---|---|---|---|")
    for c in sorted({r["client"] for r in rows}):
        for t in sorted({r["task"] for r in rows if r["client"]==c}):
            cells = {r["run"]: r["analysis"]["behaviour"] + (" (dup)" if r["metrics"]["duplicate_documents"] else "") for r in rows if r["client"]==c and r["task"]==t}
            out.append(f"| {c} | {t} | " + " | ".join(cells.get(i, "-") for i in (1,2,3)) + " |")
    out.append("")
    dup_cross = "8 of 9 runs created a second PO - every retry minted a new key (results/dup01-keys)"
    same = sum(1 for r in rows if r["analysis"]["behaviour"] in ("reused_key","verified_no_retry","new_key_rejected") and not r["metrics"]["duplicate_documents"])
    dups = sum(1 for r in rows if r["metrics"]["duplicate_documents"])
    out.append(f"**Contrast with dup_01_retry_storm.** There the retry came from a fresh session with no memory of the key and {dup_cross}. Here, within the session, {dups} of {len(rows)} runs produced a duplicate and {same} handled the timeout without one - one by replaying the same key (kernel `replayed`), the rest by looking (`search_documents`, `get_document`, `trace_document`) and continuing with the document that exists. The idempotency gap is a cross-session limitation: an agent that still holds its key uses it or checks; an agent that has forgotten it cannot, and the kernel cannot tell a repeated intent from a new one (DESIGN.md §8.2). The runs are 44 of the planned 45: the Codespace restarted during google_adk's last run (p2p_09 run 3) and the re-run was refused by Google with `403 PERMISSION_DENIED: Your project has been denied access`; Google's one `not_injected` row is a 503 before its first call.\n")
(R / "README.md").write_text("\n".join(out) + "\n")
print(R / "README.md")
