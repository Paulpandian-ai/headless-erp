"""Deterministic skill runners used when LLM_PROVIDER=none (and as the eval's in-process oracle).

Each runner follows the same discipline the LLM loop is prompted with: simulate, inspect, commit
with a fresh idempotency key; stop with input-required on approval.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from anerp.core.envelope import Principal
from anerp.mcp_server.registry import call_tool


@dataclass
class SkillResult:
    ok: bool
    text: str
    documents: dict[str, str] = field(default_factory=dict)
    approval_request_id: str | None = None
    input_required: bool = False
    blocked: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)


class Runner:
    def __init__(self, principal: Principal, task_id: str) -> None:
        self.principal = principal
        self.task_id = task_id
        self.result = SkillResult(ok=True, text="")

    def _key(self, step: str) -> str:
        return f"{self.task_id}-{step}-{uuid.uuid4().hex[:8]}"

    def query(self, name: str, **payload: Any) -> dict[str, Any]:
        r = call_tool(name, payload, self.principal)
        self.result.steps.append({"tool": name, "mode": "query", "ok": r.get("ok")})
        return r.get("result", {}) if r.get("ok") else r

    def write(self, name: str, step: str, **payload: Any) -> dict[str, Any] | None:
        """simulate -> commit. Returns the commit response, or None when blocked (result updated)."""
        sim = call_tool(name, {**payload, "mode": "simulate"}, self.principal)
        self.result.steps.append(
            {
                "tool": name,
                "mode": "simulate",
                "ok": sim.get("ok"),
                "policy": (sim.get("policy") or {}).get("decision"),
            }
        )
        if not sim.get("ok"):
            self.result.ok = False
            self.result.blocked = {"tool": name, "error": sim.get("error")}
            self.result.text = (
                f"{name} failed validation: {sim['error']['code']}: {sim['error']['message']}"
            )
            return None
        if sim.get("commit_would_fail_with"):
            self.result.ok = False
            self.result.blocked = {
                "tool": name,
                "policy": sim.get("policy"),
                "would_fail_with": sim["commit_would_fail_with"],
                "projected_effects": sim.get("projected_effects"),
            }
            self.result.text = (
                f"{name} would fail with {sim['commit_would_fail_with']}: "
                + "; ".join(sim["policy"]["reasons"])
            )
            return None
        commit = call_tool(
            name,
            {
                **payload,
                "mode": "commit",
                "idempotency_key": self._key(step),
                "simulation_id": sim["simulation_id"],
            },
            self.principal,
        )
        self.result.steps.append(
            {"tool": name, "mode": "commit", "ok": commit.get("ok"), "status": commit.get("status")}
        )
        if not commit.get("ok"):
            self.result.ok = False
            self.result.blocked = {"tool": name, "error": commit.get("error")}
            self.result.text = (
                f"{name} commit failed: {commit['error']['code']}: {commit['error']['message']}"
            )
            return None
        doc = commit.get("document") or {}
        if doc.get("number"):
            self.result.documents[doc["type"]] = doc["number"]
        if commit.get("approval_request"):
            self.result.approval_request_id = commit["approval_request"]["id"]
            self.result.input_required = True
        return commit


def procure_to_pay(
    principal: Principal, task_id: str, params: dict[str, Any], state: dict[str, Any]
) -> SkillResult:
    """params: supplier, lines[{sku, qty, unit_cost}], invoice_lines?, pay (default true), supplier_reference?"""
    r = Runner(principal, task_id)
    po_number = state.get("po")
    if po_number is None:
        commit = r.write(
            "create_purchase_order",
            "po",
            supplier=params["supplier"],
            lines=params["lines"],
            memo=params.get("memo", f"A2A task {task_id}"),
        )
        if commit is None:
            return r.result
        po_number = commit["document"]["number"]
        state["po"] = po_number
        if r.result.input_required:
            r.result.text = f"Purchase order {po_number} created in draft; total exceeds the approval threshold. Approval request {r.result.approval_request_id} is pending for a human approver. Resume this task once approved."
            return r.result
    po = r.query("get_document", id_or_number=po_number)
    if po.get("status") == "draft":
        pending = [a for a in po.get("approval_requests", []) if a["status"] == "pending"]
        r.result.input_required = True
        r.result.approval_request_id = pending[0]["id"] if pending else None
        r.result.text = f"Purchase order {po_number} is still awaiting approval."
        return r.result
    if po.get("status") == "cancelled":
        r.result.ok = False
        r.result.text = f"Purchase order {po_number} was cancelled (approval rejected)."
        return r.result
    if po.get("status") == "approved" and r.write("receive_goods", "grn", po=po_number) is None:
        return r.result
    inv_number = state.get("invoice")
    if inv_number is None and po.get("status") not in ("invoiced",):
        lines = params.get("invoice_lines") or params["lines"]
        commit = r.write(
            "post_supplier_invoice",
            "sinv",
            po=po_number,
            supplier_reference=params.get(
                "supplier_reference", f"{params['supplier']}-{task_id[:6]}"
            ),
            lines=lines,
        )
        if commit is None:
            return r.result
        inv_number = commit["document"]["number"]
        state["invoice"] = inv_number
    if (
        params.get("pay", True)
        and inv_number
        and r.write("pay_supplier", "pay", invoice=inv_number) is None
    ):
        return r.result
    r.result.text = "Procure-to-pay complete: " + ", ".join(
        f"{k} {v}" for k, v in r.result.documents.items()
    )
    return r.result


def order_to_cash(
    principal: Principal, task_id: str, params: dict[str, Any], state: dict[str, Any]
) -> SkillResult:
    """params: customer, lines[{sku, qty, unit_price?}], collect (default true)"""
    r = Runner(principal, task_id)
    so_number = state.get("so")
    if so_number is None:
        commit = r.write(
            "create_sales_order",
            "so",
            customer=params["customer"],
            lines=params["lines"],
            memo=params.get("memo", f"A2A task {task_id}"),
        )
        if commit is None:
            return r.result
        so_number = commit["document"]["number"]
        state["so"] = so_number
    if r.write("ship_order", "shp", so=so_number) is None:
        return r.result
    commit = r.write("issue_customer_invoice", "cinv", so=so_number)
    if commit is None:
        return r.result
    if (
        params.get("collect", True)
        and r.write("record_customer_payment", "rcpt", invoice=commit["document"]["number"]) is None
    ):
        return r.result
    r.result.text = "Order-to-cash complete: " + ", ".join(
        f"{k} {v}" for k, v in r.result.documents.items()
    )
    return r.result


def period_close(
    principal: Principal, task_id: str, params: dict[str, Any], state: dict[str, Any]
) -> SkillResult:
    r = Runner(principal, task_id)
    checklist = r.query("get_period", period_code=params["period"])
    readiness = checklist.get("close_readiness", {})
    if not readiness.get("ready"):
        r.result.ok = False
        r.result.blocked = readiness
        r.result.text = (
            f"Period {params['period']} cannot close: " + "; ".join(readiness.get("blockers", []))
            or "not ready"
        )
        return r.result
    if r.write("close_period", "close", period=params["period"]) is None:
        return r.result
    r.result.text = (
        f"Period {params['period']} closed. Warnings: {readiness.get('warnings') or 'none'}"
    )
    return r.result


def explain_balance(
    principal: Principal, task_id: str, params: dict[str, Any], state: dict[str, Any]
) -> SkillResult:
    r = Runner(principal, task_id)
    data = r.query(
        "explain_balance",
        account_code=params["account_code"],
        period_code=params.get("period_code"),
    )
    bal = data.get("balance", {})
    groups = ", ".join(
        f"{g['source_type']}: {g['net_cents']} cents ({g['count']} lines)"
        for g in data.get("by_source_type", [])
    )
    r.result.text = f"Account {params['account_code']} net {bal.get('net_cents')} cents. Movements by source: {groups or 'none'}. Reversal pairs: {len(data.get('reversal_pairs', []))}."
    r.result.blocked = data
    return r.result


SKILLS = {
    "procure-to-pay": procure_to_pay,
    "order-to-cash": order_to_cash,
    "period-close": period_close,
    "explain-balance": explain_balance,
}
