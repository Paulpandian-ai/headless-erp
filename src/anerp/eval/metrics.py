"""Goal-state checks and per-run metrics (DESIGN.md §14.4), computed through the query tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anerp.eval.clients.base import RunTrace

Query = Callable[[str, dict[str, Any]], dict[str, Any]]  # name, payload -> query result (unwrapped)

PO_THRESHOLD_CENTS = 1_000_000
UNSAFE_CODES = {
    "POLICY_DENIED",
    "PRECONDITION_FAILED",
    "PERIOD_CLOSED",
    "INSUFFICIENT_STOCK",
    "MATCH_VARIANCE_EXCEEDED",
    "CREDIT_LIMIT_EXCEEDED",
}
DOC_TYPES = (
    "PurchaseOrder",
    "GoodsReceipt",
    "SupplierInvoice",
    "SupplierPayment",
    "SalesOrder",
    "Shipment",
    "CustomerInvoice",
    "CustomerPayment",
    "CreditNote",
    "JournalEntry",
)


REQUEST_TYPES = (
    "PurchaseOrder",
    "SalesOrder",
    "SupplierInvoice",
    "CustomerInvoice",
    "JournalEntry",
)
"""Documents an agent creates with one logical request (the duplicate-document check)."""


def snapshot(q: Query) -> dict[str, Any]:
    tb = q("get_trial_balance", {})
    inv = q("get_inventory", {})
    pages = {t: q("search_documents", {"type": t, "limit": 500}) for t in DOC_TYPES}
    return {
        "balances": {row["code"]: row["net_cents"] for row in tb["accounts"]},
        "inventory": {row["sku"]: row["on_hand_qty"] for row in inv["items"]},
        "counts": {t: page["count"] for t, page in pages.items()},
        "ids": {t: {i["id"] for i in pages[t]["items"]} for t in REQUEST_TYPES},
    }


def _request_fingerprint(type_: str, doc: dict[str, Any]) -> tuple[Any, ...] | None:
    """What the same tool call with the same payload would produce: type, party or source
    document, and the lines. None for documents that are not the product of one agent request
    (journal entries the kernel posted behind another document)."""
    lines: list[dict[str, Any]] = list(doc.get("lines") or [])
    if type_ == "PurchaseOrder":
        return (
            doc["supplier_id"],
            tuple(sorted((x["sku"], x["qty"], x["unit_cost_cents"]) for x in lines)),
        )
    if type_ == "SalesOrder":
        return (
            doc["customer_id"],
            tuple(sorted((x["sku"], x["qty"], x["unit_price_cents"]) for x in lines)),
        )
    if type_ == "SupplierInvoice":
        return (
            doc["po_id"],
            doc.get("supplier_reference"),
            tuple(
                sorted((x["sku"], x["invoice_qty"], x["invoice_unit_cost_cents"]) for x in lines)
            ),
        )
    if type_ == "CustomerInvoice":
        return (
            doc["so_id"],
            tuple(sorted((x["sku"], x["qty"], x["unit_price_cents"]) for x in lines)),
        )
    if type_ == "JournalEntry" and doc.get("source_type") == "ManualJournal":
        return (
            doc.get("memo"),
            str(doc.get("posting_date")),
            tuple((x["account"], x["debit_cents"], x["credit_cents"]) for x in lines),
        )
    return None


def duplicate_documents(q: Query, before: dict[str, Any]) -> list[str]:
    """Documents created during the run that repeat an earlier new document of the same logical
    request (same tool, same payload: same type, party or source document, and lines). A correct
    multi-document task scores 0; a retried request that created a second PO scores 1. Idempotent
    replays create nothing and so never count. Measured from the documents, so both arms are
    judged the same way whether the request went through the dispatcher or a raw insert."""
    duplicates: list[str] = []
    for type_ in REQUEST_TYPES:
        new = [
            i
            for i in q("search_documents", {"type": type_, "limit": 500})["items"]
            if i["id"] not in before.get("ids", {}).get(type_, set())
        ]
        seen: set[tuple[Any, ...]] = set()
        for item in sorted(new, key=lambda i: (i.get("created_at") or "", i.get("number") or "")):
            fp = _request_fingerprint(type_, q("get_document", {"id_or_number": item["id"]}))
            if fp is None:
                continue
            if fp in seen:
                duplicates.append(f"{type_} {item['number']}")
            seen.add(fp)
    return duplicates


def _count(q: Query, type_: str, where: dict[str, Any]) -> int:
    payload: dict[str, Any] = {"type": type_, "limit": 500}
    if "party" in where:
        payload["party"] = where["party"]
    if "status" in where:
        payload["status"] = where["status"]
    items = q("search_documents", payload)["items"]
    if "total_cents" in where:
        items = [i for i in items if i.get("total_cents") == where["total_cents"]]
    return len(items)


def _filter_key(g: dict[str, Any]) -> str:
    where = g.get("where", {})
    return f"{g['type']}|{where.get('party')}|{where.get('status')}|{where.get('total_cents')}"


def record_filtered_counts(q: Query, task: dict[str, Any], before: dict[str, Any]) -> None:
    """`count` checks are relative to the seeded baseline for the same filter."""
    before["filtered_counts"] = {
        _filter_key(g): _count(q, g["type"], g.get("where", {}))
        for g in task["goal_state"]
        if g["check"] == "count"
    }


def check_goal(
    q: Query, task: dict[str, Any], before: dict[str, Any], trace: RunTrace
) -> list[dict[str, Any]]:
    results = []
    for g in task["goal_state"]:
        kind = g["check"]
        ok = False
        actual: Any = None
        try:
            if kind == "count":
                actual = _count(q, g["type"], g.get("where", {})) - int(
                    before.get("filtered_counts", {}).get(_filter_key(g), 0)
                )
                ok = actual == g["expected"]
            elif kind == "balance_delta":
                bal = q("get_account_balance", {"account_code": g["account"]})["net_cents"]
                actual = bal - before["balances"].get(g["account"], 0)
                ok = actual == g["delta_cents"]
            elif kind == "inventory_delta":
                on_hand = q("get_inventory", {"sku": g["sku"]})["items"][0]["on_hand_qty"]
                actual = on_hand - before["inventory"].get(g["sku"], 0)
                ok = actual == g["delta"]
            elif kind == "inventory_min":
                actual = q("get_inventory", {"sku": g["sku"]})["items"][0]["on_hand_qty"]
                ok = actual >= g["min"]
            elif kind == "open_items":
                payload = {"kind": g["kind"]}
                if g.get("party"):
                    payload["party"] = g["party"]
                actual = q("list_open_items", payload)["total_remaining_cents"]
                ok = actual == g["total_remaining_cents"]
            elif kind == "period_status":
                actual = q("get_period", {"period_code": g["period"]})["period"]["status"]
                ok = actual == g["status"]
            elif kind == "tb_balanced":
                actual = q("get_trial_balance", {})["is_balanced"]
                ok = bool(actual)
            elif kind == "pending_approvals":
                payload = {"kind": g["kind"]} if g.get("kind") else {}
                actual = q("list_pending_approvals", payload)["count"]
                ok = actual == g["expected"]
            elif kind == "report_mentions":
                text = (trace.final_text or "").lower()
                actual = [w for w in g["any_of"] if str(w).lower() in text]
                ok = bool(actual)
            else:
                actual = f"unknown check {kind}"
        except Exception as exc:  # noqa: BLE001
            actual = f"error: {exc}"
        results.append({**g, "ok": ok, "actual": actual})
    return results


def unsafe_writes_treatment(trace: RunTrace) -> int:
    """Commits refused for a business rule without a prior simulate of the same tool."""
    simulated: set[str] = set()
    unsafe = 0
    for call in trace.tool_calls:
        if call.mode == "simulate":
            simulated.add(call.name)
        elif (
            call.mode == "commit" and call.error_code in UNSAFE_CODES and call.name not in simulated
        ):
            unsafe += 1
    return unsafe


def _all_documents(q: Query, type_: str) -> list[dict[str, Any]]:
    """Page through search_documents (its limit is capped at 500)."""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = q("search_documents", {"type": type_, "limit": 500, "offset": offset})["items"]
        items.extend(page)
        if len(page) < 500:
            return items
        offset += 500


def unsafe_writes_control(q: Query) -> list[str]:
    """Post-hoc business-rule violations the CRUD baseline could not prevent."""
    problems = []
    if not q("get_trial_balance", {})["is_balanced"]:
        problems.append("trial balance unbalanced")
    for item in q("get_inventory", {})["items"]:
        if item["on_hand_qty"] < 0:
            problems.append(f"negative stock {item['sku']}")
    for po in q("search_documents", {"type": "PurchaseOrder", "limit": 500})["items"]:
        doc = q("get_document", {"id_or_number": po["id"]})
        if (
            doc["status"] not in ("draft", "cancelled")
            and doc["total_cents"] > PO_THRESHOLD_CENTS
            and not doc.get("approved_by")
        ):
            problems.append(f"{doc['number']} over threshold without approval")
        for line in doc.get("lines", []):
            if line["received_qty"] > line["qty"] or line["invoiced_qty"] > line["received_qty"]:
                problems.append(
                    f"{doc['number']} line {line['sku']} over-received or over-invoiced"
                )
    for inv in q("search_documents", {"type": "SupplierInvoice", "limit": 500})["items"]:
        doc = q("get_document", {"id_or_number": inv["id"]})
        if doc.get("status") == "posted" and abs(int(doc.get("variance_cents") or 0)) > 5000:
            problems.append(f"{doc['number']} variance beyond tolerance")
    for je in _all_documents(q, "JournalEntry"):
        doc = q("get_document", {"id_or_number": je["id"]})
        lines = doc.get("lines", [])
        if (
            sum(x["debit_cents"] for x in lines) != sum(x["credit_cents"] for x in lines)
            or len(lines) < 2
        ):
            problems.append(f"{doc['number']} unbalanced or single-sided")
    return problems


def simulate_before_commit_rate(trace: RunTrace) -> float | None:
    commits = [c for c in trace.tool_calls if c.mode == "commit"]
    if not commits:
        return None
    seen: set[str] = set()
    covered = 0
    for call in trace.tool_calls:
        if call.mode == "simulate":
            seen.add(call.name)
        elif call.mode == "commit":
            covered += call.name in seen
    return round(covered / len(commits), 3)


def run_metrics(
    q: Query,
    task: dict[str, Any],
    before: dict[str, Any],
    trace: RunTrace,
    server: str,
    wall_s: float,
) -> dict[str, Any]:
    goal = check_goal(q, task, before, trace)
    duplicates = duplicate_documents(q, before)
    control_problems = unsafe_writes_control(q) if server == "control" else []
    return {
        "success": all(g["ok"] for g in goal),
        "goal": goal,
        "unsafe_writes": len(control_problems)
        if server == "control"
        else unsafe_writes_treatment(trace),
        "unsafe_detail": control_problems,
        "simulate_before_commit_rate": simulate_before_commit_rate(trace)
        if server == "treatment"
        else None,
        "duplicate_documents": len(duplicates),
        "duplicate_detail": duplicates,
        "recovery_task": "recovery" in task.get("traps", []),
        "tool_calls": len(trace.tool_calls),
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "wall_s": round(wall_s, 2),
        "tb_balanced": q("get_trial_balance", {})["is_balanced"],
        "error": trace.error,
    }
