"""A small tool-calling loop whose only tools are the anerp tool surface, called in-process."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from anerp.a2a_agent.llm.base import LLMClient, ToolCall
from anerp.core.envelope import Principal
from anerp.mcp_server.registry import call_tool, mcp_tools

log = logging.getLogger("anerp.a2a.loop")

SYSTEM_PROMPT = """You are anerp-finance-agent, an ERP operations agent. You have the anerp tool surface.
Rules you never break:
1. Before any commit, call the same tool with mode="simulate" and read validation, policy.decision and projected_effects.
2. Commit with mode="commit", the simulation_id, and a NEW idempotency_key of the form '<task>-<step>-<8 hex>'. If a commit times out, retry with the SAME key.
3. If a response contains policy.decision == "requires_approval", an approval_request, or error code REQUIRES_APPROVAL: stop, report the approval request id and projected effects, and wait for a human. Do not try to approve yourself.
4. On POLICY_DENIED / CREDIT_LIMIT_EXCEEDED / INSUFFICIENT_STOCK / MATCH_VARIANCE_EXCEEDED / PERIOD_CLOSED: do not retry unchanged. Explain the reason and propose the safe alternative (partial quantity, payment first, re-date, escalate).
5. Use get_document / list_open_items / get_trial_balance to verify state instead of assuming.
Finish with a short report: documents created (numbers), receipts, journal entries, and anything blocked."""


@dataclass
class LoopResult:
    text: str
    steps: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    approval_request_id: str | None = None
    input_required: bool = False
    usage: dict[str, int] = field(default_factory=dict)


def _tools_for_llm() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in mcp_tools()
    ]


def _approval_id(result: dict[str, Any]) -> str | None:
    if result.get("approval_request"):
        return str(result["approval_request"]["id"])
    err = result.get("error") or {}
    if err.get("code") == "REQUIRES_APPROVAL":
        return str(err.get("details", {}).get("approval_request_id"))
    return None


def run_loop(
    llm: LLMClient,
    user_text: str,
    principal: Principal,
    *,
    max_steps: int = 30,
    task_prefix: str | None = None,
) -> LoopResult:
    task_prefix = task_prefix or uuid.uuid4().hex[:8]
    tools = _tools_for_llm()
    messages = llm.start(SYSTEM_PROMPT, user_text)
    result = LoopResult(text="", steps=0)
    for _ in range(max_steps):
        turn = llm.complete(SYSTEM_PROMPT, messages, tools)
        result.steps += 1
        for k, v in turn.usage.items():
            result.usage[k] = result.usage.get(k, 0) + v
        llm.append_assistant(messages, turn)
        if not turn.tool_calls:
            result.text = turn.text
            return result
        outputs: list[tuple[ToolCall, str, bool]] = []
        for call in turn.tool_calls:
            out = call_tool(call.name, call.arguments, principal)
            result.tool_calls.append(
                {
                    "name": call.name,
                    "arguments": call.arguments,
                    "ok": out.get("ok"),
                    "error_code": (out.get("error") or {}).get("code"),
                    "mode": call.arguments.get("mode"),
                }
            )
            outputs.append((call, json.dumps(out, default=str), not out.get("ok", False)))
            approval = _approval_id(out)
            if approval:
                result.approval_request_id = approval
                result.input_required = True
        llm.append_tool_results(messages, outputs)
        if result.input_required:
            # One more model turn to produce the hand-off text, then stop.
            final = llm.complete(SYSTEM_PROMPT, messages, tools)
            result.text = final.text or f"Approval required: request {result.approval_request_id}"
            return result
    result.text = "Stopped: step limit reached."
    return result
