"""MCP prompts: short playbooks that teach simulate-before-commit and idempotency discipline."""

from __future__ import annotations

import mcp_types as types

DISCIPLINE = (
    "Discipline for every write:\n"
    '1. Call the tool with mode="simulate" first and read validation.errors, policy.decision and projected_effects.\n'
    "2. If policy.decision is deny, do not retry unchanged: report the reasons. If requires_approval, stop and hand off to a human approver (list_pending_approvals shows the request).\n"
    "3. Commit with mode=\"commit\", a fresh idempotency_key (e.g. '<task>-<step>-<uuid>') and the simulation_id. Reuse the SAME key if you retry the same commit after a timeout.\n"
    "4. Keep the receipt id; every commit names its compensating_tool if you need to undo it.\n"
)

PROMPTS: dict[str, dict[str, str]] = {
    "procure_to_pay_playbook": {
        "description": "How to run a purchase from order to payment safely.",
        "text": (
            "Procure-to-pay in anerp:\n"
            "create_purchase_order -> (approve_purchase_order by a human if the PO is draft) -> receive_goods -> post_supplier_invoice -> pay_supplier.\n"
            "Use get_document to check the PO status before each step; use list_open_items(kind='ap') to see what is payable.\n"
            "post_supplier_invoice performs a three-way match: quantities above receipts or prices outside tolerance return MATCH_VARIANCE_EXCEEDED. "
            "Simulate shows the variance amount so you can report it instead of forcing the post.\n"
            + DISCIPLINE
        ),
    },
    "order_to_cash_playbook": {
        "description": "How to take a sales order through shipment, invoice and cash.",
        "text": (
            "Order-to-cash in anerp:\n"
            "create_sales_order -> ship_order -> issue_customer_invoice -> record_customer_payment (issue_credit_note for corrections).\n"
            "create_sales_order checks credit exposure (open AR + this order) against the customer's limit: CREDIT_LIMIT_EXCEEDED means reduce the order or collect cash first. "
            "ship_order checks on-hand stock: INSUFFICIENT_STOCK means receive goods first or ship a partial quantity.\n"
            + DISCIPLINE
        ),
    },
    "period_close_checklist": {
        "description": "How to check and close a fiscal period.",
        "text": (
            "Period close in anerp:\n"
            "1. get_period(period_code) returns the close-readiness checklist: blockers (blocked supplier invoices, unbalanced trial balance) and warnings (draft POs, open GR/IR, uninvoiced shipments).\n"
            "2. Resolve blockers with the normal tools (reverse_supplier_invoice, post_supplier_invoice...). Never delete anything; reversals are the only correction path.\n"
            "3. simulate close_period, read the checklist in projected_effects.details, then commit. reopen_period (with a reason) is the compensating tool.\n"
            + DISCIPLINE
        ),
    },
}


def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(name=name, description=p["description"], arguments=[])
        for name, p in PROMPTS.items()
    ]


def get_prompt(name: str) -> types.GetPromptResult:
    p = PROMPTS[name]
    return types.GetPromptResult(
        description=p["description"],
        messages=[
            types.PromptMessage(role="user", content=types.TextContent(type="text", text=p["text"]))
        ],
    )
