"""AgentExecutor: routes a task to a skill runner (LLM loop when a provider is configured)."""

from __future__ import annotations

import json
import logging
from typing import Any

from a2a.helpers.proto_helpers import (
    get_data_parts,
    get_text_parts,
    new_data_part,
    new_task_from_user_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Task

from anerp.a2a_agent.llm.base import make_client
from anerp.a2a_agent.loop import run_loop
from anerp.a2a_agent.skills import SKILLS
from anerp.config import get_settings
from anerp.core.envelope import Principal

log = logging.getLogger("anerp.a2a")

AGENT_SCOPES = [
    "procurement:write",
    "sales:write",
    "finance:*",
    "masterdata:write",
    "*:read",
    "approvals:write",
]


class AnerpAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}  # task_id -> skill state (PO number, ...)

    def _principal(self, context: RequestContext) -> Principal:
        """The A2A agent's own actor; the delegating agent is recorded as on_behalf_of."""
        meta = context.metadata or {}
        headers = getattr(context.call_context, "state", {}) or {}
        caller = meta.get("caller") or headers.get("caller") or "agent:unknown-delegator"
        return Principal(
            subject="agent:anerp-finance", kind="agent", scopes=AGENT_SCOPES, token_id=None
        ).model_copy(update={"_on_behalf_of": caller})

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task is None and context.message is not None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
            context.current_task = task
        task_id = context.task_id or (context.current_task.id if context.current_task else "task")
        context_id = context.context_id or (
            context.current_task.context_id if context.current_task else task_id
        )
        updater = TaskUpdater(event_queue, task_id, context_id)
        await updater.start_work()
        text = "\n".join(get_text_parts(context.message.parts)) if context.message else ""
        data_parts = get_data_parts(context.message.parts) if context.message else []
        structured = data_parts[0] if data_parts else None
        principal = self._principal(context)
        state = self._state.setdefault(task_id, {})
        if not isinstance(structured, dict) and state.get("_skill"):
            structured = {
                "skill": state["_skill"],
                "params": state["_params"],
            }  # resume after input-required
        try:
            if isinstance(structured, dict) and structured.get("skill") in SKILLS:
                skill = structured["skill"]
                state["_skill"], state["_params"] = skill, structured.get("params", {})
                result = SKILLS[skill](principal, task_id, structured.get("params", {}), state)
                payload = {
                    "skill": skill,
                    "ok": result.ok,
                    "documents": result.documents,
                    "approval_request_id": result.approval_request_id,
                    "blocked": result.blocked,
                    "steps": result.steps,
                }
                message = updater.new_agent_message(
                    [new_text_part(result.text), new_data_part(payload)]
                )
                if result.input_required:
                    await updater.requires_input(message)
                elif result.ok:
                    await updater.complete(message)
                else:
                    await updater.failed(message)
                return
            llm = make_client(get_settings().llm_provider)
            if llm is None:
                await updater.failed(
                    updater.new_agent_message(
                        [
                            new_text_part(
                                "No LLM provider configured (LLM_PROVIDER=none). Send a data part {skill, params} for deterministic execution, or set LLM_PROVIDER."
                            )
                        ]
                    )
                )
                return
            loop = run_loop(llm, text or json.dumps(structured), principal, task_prefix=task_id[:8])
            payload = {
                "tool_calls": loop.tool_calls,
                "steps": loop.steps,
                "approval_request_id": loop.approval_request_id,
                "usage": loop.usage,
            }
            message = updater.new_agent_message([new_text_part(loop.text), new_data_part(payload)])
            if loop.input_required:
                await updater.requires_input(message)
            else:
                await updater.complete(message)
        except Exception as exc:  # noqa: BLE001
            log.exception("a2a task %s failed", task_id)
            await updater.failed(
                updater.new_agent_message([new_text_part(f"internal error: {exc}")])
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or "task"
        updater = TaskUpdater(event_queue, task_id, context.context_id or task_id)
        await updater.cancel(updater.new_agent_message([new_text_part("cancelled")]))


__all__ = ["AnerpAgentExecutor", "Task"]
