"""Agent Card for anerp-finance-agent (DESIGN.md §12)."""

from __future__ import annotations

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from anerp import __version__

SKILLS = [
    (
        "procure-to-pay",
        "Procure to pay",
        "Given a supplier, items, quantities and prices, create and progress a purchase order through receipt, invoice and payment, respecting approval thresholds.",
        ["procurement", "ap"],
    ),
    (
        "order-to-cash",
        "Order to cash",
        "Create a sales order, ship, invoice and collect payment, respecting credit limits and stock.",
        ["sales", "ar"],
    ),
    (
        "period-close",
        "Period close",
        "Run the close-readiness checklist for a period and close it if clean; otherwise report blockers.",
        ["finance", "gl"],
    ),
    (
        "explain-balance",
        "Explain balance",
        "Explain the movements behind an account balance for a period.",
        ["finance", "troubleshooting"],
    ),
]


def build_card(public_url: str) -> AgentCard:
    base = public_url.rstrip("/")
    return AgentCard(
        name="anerp-finance-agent",
        description="Task-level finance agent over the anerp headless ERP kernel. Structured input (data part) is preferred: {skill, params}. Approvals return input-required with the ApprovalRequest id.",
        version=__version__,
        documentation_url=f"{base}/",
        supported_interfaces=[AgentInterface(url=f"{base}/a2a", protocol_binding="JSONRPC")],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id=sid,
                name=name,
                description=desc,
                tags=tags,
                examples=[f'{{"skill": "{sid}", "params": {{...}}}}'],
            )
            for sid, name, desc, tags in SKILLS
        ],
    )
