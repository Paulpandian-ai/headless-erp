"""The operation dispatcher: envelope -> validate -> project -> policy -> simulate | commit.

This is the only write path in anerp (DESIGN.md §3 "single dispatcher principle").
"""

from __future__ import annotations

import json as _json
import logging
import time
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from anerp.approvals.models import ApprovalRequest
from anerp.config import get_settings
from anerp.core.context import ToolContext
from anerp.core.envelope import Actor, Envelope, Principal
from anerp.core.errors import AnerpError, ErrorCode
from anerp.core.hashing import canonical_json, hash_obj
from anerp.core.ids import iso, new_ulid, utcnow
from anerp.core.projection import DocumentEffect, EventSpec, Projection
from anerp.core.registry import BaseTool, QueryTool, WriteTool, registry
from anerp.core.requestlog import (
    RequestLogEntry,
    SimulationRecord,
    redact,
    request_log,
    simulation_expiry,
    simulations,
)
from anerp.db import new_session
from anerp.events.log import emit
from anerp.ledger import idempotency
from anerp.ledger.models import IdempotencyRecord, Receipt
from anerp.ledger.posting import post_journal
from anerp.ledger.receipts import keyring, receipt_message, receipt_to_dict, snapshot_hash
from anerp.ledger.sequences import allocate_number
from anerp.policy.engine import get_engine
from anerp.policy.rules import PolicyResult

log = logging.getLogger("anerp.dispatch")

_INTERNAL_MESSAGE = (
    "internal error; the details are in the server log under request_id {request_id}"
)


def _jsonable(obj: Any) -> Any:
    return _json.loads(canonical_json(obj))


def _state_versions(rows: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        sv = getattr(row, "state_version", None)
        if sv is not None:
            out[f"{type(row).__name__}:{row.id}"] = int(sv)
    return out


def _error_response(
    exc: AnerpError, *, mode: str, request_id: str, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": False,
        "mode": mode,
        "request_id": request_id,
        "error": exc.to_dict(),
    }
    if extra:
        body.update(extra)
    return body


def _doc_summary(effect: Any) -> dict[str, Any] | None:
    if effect is None:
        return None
    inst = effect.instance
    return {
        "type": effect.type,
        "id": inst.id,
        "number": getattr(inst, "number", None)
        or getattr(inst, "code", None)
        or getattr(inst, "sku", None),
        "status": getattr(inst, "status", None),
        "action": effect.action,
    }


def _projection_dict(projection: Projection, *, committed: bool) -> dict[str, Any]:
    docs = []
    for eff in projection.documents:
        d = _doc_summary(eff) or {}
        d["fields"] = _jsonable(
            eff.projected_fields if not committed else eff.instance.model_dump(mode="json")
        )
        docs.append(d)
    open_items = []
    for eff in projection.open_items:
        d = _doc_summary(eff) or {}
        d["fields"] = _jsonable(
            eff.projected_fields if not committed else eff.instance.model_dump(mode="json")
        )
        open_items.append(d)
    return {
        "documents": docs,
        "journal_entry": projection.journal.as_dict() if projection.journal else None,
        "open_items": open_items,
        "inventory_deltas": [
            {"sku": d.sku, "qty_delta": d.qty_delta} for d in projection.inventory
        ],
        "balance_deltas": projection.balance_deltas(),
        "events": [e.type for e in projection.events],
        **({"details": _jsonable(projection.extra)} if projection.extra else {}),
    }


def _log(
    entry_kwargs: dict[str, Any],
) -> None:
    request_log.add(RequestLogEntry(**entry_kwargs))


class _Timer:
    def __init__(self) -> None:
        self.started = utcnow()
        self._t0 = time.perf_counter()

    @property
    def ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 2)


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def _require_principal(principal: Principal | None) -> AnerpError | None:
    """Outside ANERP_ENV=test a call without a principal is unauthenticated: the envelope's
    self-declared actor (and therefore `actor.kind`, which `human_approval_only` relies on) is
    only believed when it comes from a token or an explicit `local_principal()`."""
    if principal is not None or get_settings().env == "test":
        return None
    return AnerpError(
        ErrorCode.UNAUTHORIZED,
        "no principal: network paths must resolve a bearer token and in-process callers must pass "
        "an explicit Principal (anerp.core.envelope.local_principal)",
        {},
    )


def resolve_actor(envelope_actor: Actor, principal: Principal | None) -> Actor:
    if principal is None:
        return envelope_actor
    return principal.to_actor(on_behalf_of=envelope_actor.on_behalf_of)


def dispatch(
    envelope: Envelope | dict[str, Any], *, principal: Principal | None = None
) -> dict[str, Any]:
    """Run one write operation. Always returns a dict; business errors are never raised."""
    request_id = new_ulid()
    timer = _Timer()
    if isinstance(envelope, dict):
        raw = envelope
        try:
            envelope = Envelope.model_validate(raw)
        except ValidationError as exc:
            err = AnerpError(
                ErrorCode.VALIDATION_ERROR,
                "invalid envelope",
                {"errors": exc.errors(include_url=False)},
            )
            return _error_response(
                err, mode=str(raw.get("mode", "simulate")), request_id=request_id
            )
    mode = envelope.mode
    tool = registry.get(envelope.tool)
    if tool is None or not isinstance(tool, WriteTool):
        err = AnerpError(
            ErrorCode.VALIDATION_ERROR,
            f"unknown write tool '{envelope.tool}'",
            {"tool": envelope.tool},
        )
        return _error_response(err, mode=mode, request_id=request_id)
    actor = resolve_actor(envelope.actor, principal)
    base_log: dict[str, Any] = {
        "request_id": request_id,
        "tool": tool.name,
        "mode": mode,
        "actor_id": actor.id,
        "actor_kind": actor.kind,
        "started_at": timer.started,
        "payload": redact(envelope.payload),
        "simulation_id": envelope.simulation_id,
        "idempotency_key": envelope.idempotency_key,
        "on_behalf_of": actor.on_behalf_of,
    }
    if (missing := _require_principal(principal)) is not None:
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": missing.code.value,
                "error_message": missing.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(missing, mode=mode, request_id=request_id)
    if principal is not None and not principal.has_scope(tool.scope):
        err = AnerpError(
            ErrorCode.FORBIDDEN,
            f"token lacks scope '{tool.scope}' required by {tool.name}",
            {"required_scope": tool.scope, "granted": principal.scopes},
        )
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": err.code.value,
                "error_message": err.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(err, mode=mode, request_id=request_id)
    try:
        payload = tool.payload_model.model_validate(envelope.payload)
    except ValidationError as exc:
        err = AnerpError(
            ErrorCode.VALIDATION_ERROR,
            f"invalid payload for {tool.name}",
            {"errors": _jsonable(exc.errors(include_url=False))},
        )
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": err.code.value,
                "error_message": err.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(err, mode=mode, request_id=request_id)

    session = new_session()
    try:
        if mode == "simulate":
            response = _simulate(
                session, tool, envelope, actor, payload, request_id, base_log, timer, principal
            )
        else:
            response = _commit(
                session, tool, envelope, actor, payload, request_id, base_log, timer, principal
            )
        return response
    except AnerpError as exc:
        session.rollback()
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": exc.code.value,
                "error_message": exc.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(exc, mode=mode, request_id=request_id)
    except Exception:  # noqa: BLE001 - convert to INTERNAL_ERROR, never leak a 500 to an agent
        session.rollback()
        log.exception("internal error in %s (%s)", tool.name, request_id)
        err = AnerpError(
            ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE.format(request_id=request_id), {}
        )
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": err.code.value,
                "error_message": err.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(err, mode=mode, request_id=request_id)
    finally:
        session.close()


def run_query(
    name: str,
    payload: dict[str, Any],
    actor: Actor,
    *,
    principal: Principal | None = None,
) -> dict[str, Any]:
    """Run a read-only tool. The session is always rolled back."""
    request_id = new_ulid()
    timer = _Timer()
    tool = registry.get(name)
    actor = resolve_actor(actor, principal)
    base_log: dict[str, Any] = {
        "request_id": request_id,
        "tool": name,
        "mode": "query",
        "actor_id": actor.id,
        "actor_kind": actor.kind,
        "started_at": timer.started,
        "payload": redact(payload),
        "on_behalf_of": actor.on_behalf_of,
    }
    if tool is None or not isinstance(tool, QueryTool):
        err = AnerpError(ErrorCode.VALIDATION_ERROR, f"unknown query tool '{name}'", {"tool": name})
        return _error_response(err, mode="query", request_id=request_id)
    if (missing := _require_principal(principal)) is not None:
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": missing.code.value,
                "error_message": missing.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(missing, mode="query", request_id=request_id)
    if principal is not None and not principal.has_scope(tool.scope):
        err = AnerpError(
            ErrorCode.FORBIDDEN,
            f"token lacks scope '{tool.scope}' required by {name}",
            {"required_scope": tool.scope},
        )
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": err.code.value,
                "error_message": err.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(err, mode="query", request_id=request_id)
    try:
        model = tool.payload_model.model_validate(payload)
    except ValidationError as exc:
        err = AnerpError(
            ErrorCode.VALIDATION_ERROR,
            f"invalid payload for {name}",
            {"errors": _jsonable(exc.errors(include_url=False))},
        )
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": err.code.value,
                "error_message": err.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(err, mode="query", request_id=request_id)
    session = new_session()
    try:
        ctx = ToolContext(session, actor, "simulate", request_id, principal=principal)
        result = tool.run(ctx, model)
        _log({**base_log, "outcome": "ok", "latency_ms": timer.ms})
        return {
            "ok": True,
            "mode": "query",
            "request_id": request_id,
            "tool": name,
            "result": _jsonable(result),
        }
    except AnerpError as exc:
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": exc.code.value,
                "error_message": exc.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(exc, mode="query", request_id=request_id)
    except Exception:  # noqa: BLE001
        log.exception("internal error in query %s (%s)", name, request_id)
        err = AnerpError(
            ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE.format(request_id=request_id), {}
        )
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": err.code.value,
                "error_message": err.message,
                "latency_ms": timer.ms,
            }
        )
        return _error_response(err, mode="query", request_id=request_id)
    finally:
        session.rollback()
        session.close()


def tool_for(name: str) -> BaseTool | None:
    return registry.get(name)


# --------------------------------------------------------------------------------------
# Simulate
# --------------------------------------------------------------------------------------
def _project_and_evaluate(
    session: Session,
    tool: WriteTool,
    actor: Actor,
    payload: BaseModel,
    request_id: str,
    mode: str,
    principal: Principal | None = None,
) -> tuple[Projection, PolicyResult, ToolContext]:
    ctx = ToolContext(session, actor, mode, request_id, principal=principal)  # type: ignore[arg-type]
    projection = tool.project(ctx, payload)
    for row in ctx.touched:
        if all(r is not row for r in projection.touched):
            projection.touched.append(row)
    facts = dict(projection.facts)
    facts.setdefault("mode", mode)
    policy = get_engine().evaluate(tool.name, facts, ctx.actor_facts())
    projection.warnings.extend(policy.warnings)
    return projection, policy, ctx


def _simulate(
    session: Session,
    tool: WriteTool,
    envelope: Envelope,
    actor: Actor,
    payload: BaseModel,
    request_id: str,
    base_log: dict[str, Any],
    timer: _Timer,
    principal: Principal | None = None,
) -> dict[str, Any]:
    try:
        projection, policy, _ctx = _project_and_evaluate(
            session, tool, actor, payload, request_id, "simulate", principal
        )
    except AnerpError as exc:
        session.rollback()
        _log(
            {
                **base_log,
                "outcome": "error",
                "error_code": exc.code.value,
                "error_message": exc.message,
                "latency_ms": timer.ms,
            }
        )
        return {
            "ok": False,
            "mode": "simulate",
            "request_id": request_id,
            "validation": {"errors": [exc.to_dict()], "warnings": []},
            "error": exc.to_dict(),
        }
    simulation_id = new_ulid()
    state_versions = _state_versions(projection.touched)
    expires = simulation_expiry()
    projected = _projection_dict(projection, committed=False)
    payload_dict = payload.model_dump(mode="json")
    simulations.put(
        SimulationRecord(
            simulation_id=simulation_id,
            tool=tool.name,
            request_hash=idempotency.request_hash(tool.name, payload_dict),
            state_versions=state_versions,
            created_at=utcnow(),
            expires_at=expires,
            projection=projected,
        )
    )
    # Simulate never writes: discard anything the projection may have staged.
    session.rollback()
    would_fail = policy.error_code if policy.decision == "deny" else None
    response: dict[str, Any] = {
        "ok": True,
        "mode": "simulate",
        "request_id": request_id,
        "simulation_id": simulation_id,
        "tool": tool.name,
        "validation": {"errors": [], "warnings": projection.warnings},
        "policy": policy.as_dict(),
        "would_commit": policy.decision == "allow"
        or (policy.decision == "requires_approval" and projection.on_requires_approval is not None),
        "commit_would_fail_with": would_fail
        or (
            "REQUIRES_APPROVAL"
            if policy.decision == "requires_approval" and projection.on_requires_approval is None
            else None
        ),
        "projected_effects": projected,
        "state_versions": state_versions,
        "expires_at": iso(expires),
        "compensating_tool": (
            {
                "name": projection.compensation.tool,
                "payload_hint": projection.compensation.payload_hint,
            }
            if projection.compensation
            else None
        ),
    }
    _log(
        {
            **base_log,
            "outcome": "simulated",
            "policy_decision": policy.decision,
            "policy": policy.as_dict(),
            "latency_ms": timer.ms,
            "state_snapshot": {
                "state_versions": state_versions,
                "facts": _jsonable(projection.facts),
            },
        }
    )
    return response


# --------------------------------------------------------------------------------------
# Commit
# --------------------------------------------------------------------------------------
def _commit(
    session: Session,
    tool: WriteTool,
    envelope: Envelope,
    actor: Actor,
    payload: BaseModel,
    request_id: str,
    base_log: dict[str, Any],
    timer: _Timer,
    principal: Principal | None = None,
) -> dict[str, Any]:
    assert envelope.idempotency_key is not None
    payload_dict = payload.model_dump(mode="json")
    req_hash = idempotency.request_hash(tool.name, payload_dict)
    existing = idempotency.lookup(session, envelope.idempotency_key)
    if existing is not None:
        if existing.request_hash != req_hash:
            raise AnerpError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                f"idempotency_key '{envelope.idempotency_key}' was used with a different payload",
                {"idempotency_key": envelope.idempotency_key, "original_tool": existing.tool_name},
            )
        return _replayed(existing, request_id, base_log, timer)

    projection, policy, ctx = _project_and_evaluate(
        session, tool, actor, payload, request_id, "commit", principal
    )
    before_hash = snapshot_hash(projection.touched)
    state_versions = _state_versions(projection.touched)
    if envelope.simulation_id:
        _check_simulation(envelope.simulation_id, tool.name, req_hash, state_versions)

    if policy.decision == "deny":
        code = ErrorCode(policy.error_code or "POLICY_DENIED")
        if code.value in tool.park_on_deny:
            return _standalone_approval(
                session,
                tool,
                projection,
                actor,
                policy,
                envelope,
                req_hash,
                before_hash,
                request_id,
                base_log,
                timer,
                kind=tool.park_on_deny[code.value],
                error_code=code,
            )
        raise AnerpError(
            code,
            "; ".join(policy.reasons) or "denied by policy",
            {
                "policy": policy.as_dict(),
                "projected_effects": _projection_dict(projection, committed=False),
            },
        )

    pending_approval = False
    if policy.decision == "requires_approval":
        if projection.on_requires_approval is None:
            return _standalone_approval(
                session,
                tool,
                projection,
                actor,
                policy,
                envelope,
                req_hash,
                before_hash,
                request_id,
                base_log,
                timer,
            )
        projection.on_requires_approval()
        pending_approval = True

    # ---- apply effects in one transaction --------------------------------------------
    hook_result: dict[str, Any] = {}
    if projection.apply_hook is not None:
        hook_result = projection.apply_hook(session) or {}
    created: list[Any] = []
    for eff in [*projection.documents, *projection.open_items]:
        inst = eff.instance
        if eff.action == "create":
            number = getattr(inst, "number", None)
            if isinstance(number, str) and (number == "" or number.endswith("(projected)")):
                inst.number = allocate_number(session, eff.type)
            session.add(inst)
            created.append(inst)
        else:
            for key, value in eff.changes.items():
                setattr(inst, key, value)
            if hasattr(inst, "touch"):
                inst.touch()
            session.add(inst)
    for delta in projection.inventory:
        item = delta.item
        item.on_hand_qty = int(item.on_hand_qty) + delta.qty_delta
        if all(item is not e.instance for e in projection.documents):
            item.touch()  # updated-effect items were already version-bumped above
        session.add(item)
    journal = post_journal(session, projection.journal) if projection.journal else None
    primary = projection.primary
    if (
        journal is not None
        and primary is not None
        and hasattr(primary.instance, "journal_entry_id")
        and getattr(primary.instance, "journal_entry_id", None) in (None, journal.id)
    ):
        primary.instance.journal_entry_id = journal.id
    session.flush()
    if primary is None and journal is not None:
        primary = DocumentEffect(
            type="JournalEntry", action="create", instance=journal, primary=True
        )
        if all(journal is not r for r in projection.touched):
            created.append(journal)

    approval_request: ApprovalRequest | None = None
    if pending_approval and primary is not None:
        approval_request = ApprovalRequest(
            kind=tool.approval_kind,
            document_type=primary.type,
            document_id=primary.instance.id,
            document_number=getattr(primary.instance, "number", None),
            tool_name=tool.name,
            requested_by=actor.id,
            reason=projection.approval_reason or "; ".join(policy.reasons),
            projected_effects_json=_projection_dict(projection, committed=False),
            expires_at=utcnow() + timedelta(hours=get_settings().approval_ttl_hours),
        )
        session.add(approval_request)
        session.flush()
        projection.events.append(
            EventSpec(
                type="approval.requested",
                summary=f"Approval requested for {primary.type} {getattr(primary.instance, 'number', primary.instance.id)}",
                document_type="ApprovalRequest",
                document=approval_request,
                extra={
                    "approval_request_id": approval_request.id,
                    "for_document_id": primary.instance.id,
                },
            )
        )

    # ---- events -----------------------------------------------------------------------
    events = []
    for spec in projection.events:
        doc = (
            spec.document if spec.document is not None else (primary.instance if primary else None)
        )
        events.append(
            emit(
                session,
                spec.type,
                document_type=spec.document_type or (primary.type if primary else None),
                document_id=getattr(doc, "id", None),
                number=getattr(doc, "number", None),
                status=getattr(doc, "status", None),
                summary=spec.summary,
                actor_id=actor.id,
                extra=spec.extra,
            )
        )

    # ---- receipt ----------------------------------------------------------------------
    after_rows = list(projection.touched)
    for inst in created:
        if all(inst is not r for r in after_rows):
            after_rows.append(inst)
    after_hash = snapshot_hash(after_rows)
    action_hash = hash_obj(
        {
            "tool_name": tool.name,
            "payload": payload_dict,
            "actor": {"id": actor.id, "kind": actor.kind, "on_behalf_of": actor.on_behalf_of},
        }
    )
    signed_at = utcnow()
    doc_id = primary.instance.id if primary else None
    message = receipt_message(tool.name, doc_id, before_hash, action_hash, after_hash, signed_at)
    signature, key_id = keyring.sign(session, message)
    receipt = Receipt(
        tool_name=tool.name,
        actor_id=actor.id,
        actor_kind=actor.kind,
        on_behalf_of=actor.on_behalf_of,
        document_type=primary.type if primary else None,
        document_id=doc_id,
        document_number=getattr(primary.instance, "number", None) if primary else None,
        before_hash=before_hash,
        action_hash=action_hash,
        after_hash=after_hash,
        signature=signature,
        public_key_id=key_id,
        signed_at=signed_at,
        idempotency_key=envelope.idempotency_key,
        payload_json=payload_dict,
        projection_json=_projection_dict(projection, committed=False),
    )
    session.add(receipt)
    session.flush()
    for ev in events:
        ev.receipt_id = receipt.id
        ev.payload_json = {**ev.payload_json, "receipt_id": receipt.id}
        session.add(ev)
    if journal is not None:
        journal.receipt_id = receipt.id
        session.add(journal)

    response: dict[str, Any] = {
        "ok": True,
        "mode": "commit",
        "status": "applied",
        "request_id": request_id,
        "tool": tool.name,
        "document": _doc_summary(primary),
        "journal_entry": {"id": journal.id, "number": journal.number} if journal else None,
        "receipt": receipt_to_dict(receipt),
        "events_emitted": [{"seq": e.seq, "type": e.type} for e in events],
        "policy": policy.as_dict(),
        "warnings": projection.warnings,
        "approval_request": (
            {"id": approval_request.id, "status": approval_request.status}
            if approval_request
            else None
        ),
        "effects": _projection_dict(projection, committed=True),
        **({"hook_result": hook_result} if hook_result else {}),
        "compensating_tool": (
            {
                "name": projection.compensation.tool,
                "payload_hint": projection.compensation.payload_hint,
            }
            if projection.compensation
            else None
        ),
    }
    if projection.secret:
        response["secret"] = projection.secret
    response = _jsonable(response)
    stored = {k: v for k, v in response.items() if k != "secret"}
    idempotency.store(session, envelope.idempotency_key, tool.name, req_hash, stored, receipt.id)
    try:
        session.commit()
    except IntegrityError:
        # Two concurrent commits with the same key both passed the lookup; the loser's insert
        # violates the primary key. The winner's effects stand: answer with its stored response.
        session.rollback()
        winner = session.get(IdempotencyRecord, envelope.idempotency_key)
        if winner is not None and winner.request_hash == req_hash:
            log.warning(
                "idempotency race on key %s (%s): returning the stored response",
                envelope.idempotency_key,
                request_id,
            )
            return _replayed(winner, request_id, base_log, timer)
        raise
    if projection.after_commit is not None:
        projection.after_commit()
    _log(
        {
            **base_log,
            "outcome": "applied",
            "policy_decision": policy.decision,
            "policy": policy.as_dict(),
            "latency_ms": timer.ms,
            "document_id": doc_id,
            "document_number": response["document"]["number"] if response.get("document") else None,
            "receipt_id": receipt.id,
            "state_snapshot": {"state_versions": state_versions},
        }
    )
    return response


def _check_simulation(
    simulation_id: str, tool_name: str, req_hash: str, current: dict[str, int]
) -> None:
    record = simulations.get(simulation_id)
    if record is None:
        raise AnerpError(
            ErrorCode.STALE_SIMULATION,
            f"simulation {simulation_id} is unknown or has expired; re-simulate",
            {"simulation_id": simulation_id},
        )
    if record.tool != tool_name or record.request_hash != req_hash:
        raise AnerpError(
            ErrorCode.STALE_SIMULATION,
            "simulation_id belongs to a different tool or payload; re-simulate",
            {"simulation_id": simulation_id},
        )
    if record.expires_at < utcnow():
        raise AnerpError(
            ErrorCode.STALE_SIMULATION,
            "simulation expired; re-simulate",
            {"simulation_id": simulation_id},
        )
    changed = {
        k: (v, current.get(k)) for k, v in record.state_versions.items() if current.get(k) != v
    }
    if changed:
        raise AnerpError(
            ErrorCode.STALE_SIMULATION,
            "state changed since simulation; re-simulate",
            {
                "simulation_id": simulation_id,
                "changed": {k: {"simulated": a, "current": b} for k, (a, b) in changed.items()},
            },
        )


def _replayed(
    record: IdempotencyRecord, request_id: str, base_log: dict[str, Any], timer: _Timer
) -> dict[str, Any]:
    replayed: dict[str, Any] = dict(record.response_json)
    replayed["status"] = "replayed"
    replayed["request_id"] = request_id
    _log(
        {
            **base_log,
            "outcome": "replayed",
            "latency_ms": timer.ms,
            "receipt_id": record.receipt_id,
            "document_id": (replayed.get("document") or {}).get("id"),
        }
    )
    return replayed


def _standalone_approval(
    session: Session,
    tool: WriteTool,
    projection: Projection,
    actor: Actor,
    policy: PolicyResult,
    envelope: Envelope,
    req_hash: str,
    before_hash: str,
    request_id: str,
    base_log: dict[str, Any],
    timer: _Timer,
    *,
    kind: str | None = None,
    error_code: ErrorCode = ErrorCode.REQUIRES_APPROVAL,
) -> dict[str, Any]:
    """Approval needed but the tool cannot persist a pending version.

    Nothing of the business projection is written. What is written, in one transaction and with a
    receipt: one pending ApprovalRequest (deduplicated on tool + request hash, so retries and
    duplicate submissions share it), its event, and the idempotency record for this key, so a
    replay of the same key returns this same REQUIRES_APPROVAL response. After the approval is
    granted the agent commits again with a new key.
    """
    assert envelope.idempotency_key is not None
    kind = kind or tool.approval_kind
    session.rollback()
    primary = projection.primary
    target = projection.approval_target
    target_type = projection.approval_target_type or (
        type(target).__name__ if target is not None else None
    )
    if target is None and primary is not None and primary.action == "update":
        target, target_type = primary.instance, primary.type
    pending = session.exec(
        select(ApprovalRequest).where(
            ApprovalRequest.tool_name == tool.name,
            ApprovalRequest.request_hash == req_hash,
            ApprovalRequest.status == "pending",
        )
    ).first()
    deduplicated = pending is not None
    if pending is None:
        pending = ApprovalRequest(
            document_type=target_type or (primary.type if primary else tool.name),
            document_id=target.id if target is not None else None,
            document_number=getattr(target, "number", None) if target is not None else None,
            tool_name=tool.name,
            kind=kind,
            request_hash=req_hash,
            payload_json=envelope.payload,
            requested_by=actor.id,
            reason="; ".join(policy.reasons),
            projected_effects_json=_projection_dict(projection, committed=False),
            expires_at=utcnow() + timedelta(hours=get_settings().approval_ttl_hours),
        )
        session.add(pending)
        session.flush()
    payload_dict = envelope.payload
    action_hash = hash_obj(
        {
            "tool_name": tool.name,
            "payload": payload_dict,
            "actor": {"id": actor.id, "kind": actor.kind, "on_behalf_of": actor.on_behalf_of},
        }
    )
    signed_at = utcnow()
    after_hash = snapshot_hash([pending])
    message = receipt_message(
        tool.name, pending.id, before_hash, action_hash, after_hash, signed_at
    )
    signature, key_id = keyring.sign(session, message)
    receipt = Receipt(
        tool_name=tool.name,
        actor_id=actor.id,
        actor_kind=actor.kind,
        on_behalf_of=actor.on_behalf_of,
        document_type="ApprovalRequest",
        document_id=pending.id,
        document_number=pending.document_number,
        before_hash=before_hash,
        action_hash=action_hash,
        after_hash=after_hash,
        signature=signature,
        public_key_id=key_id,
        signed_at=signed_at,
        idempotency_key=envelope.idempotency_key,
        payload_json=payload_dict,
        projection_json=_projection_dict(projection, committed=False),
    )
    session.add(receipt)
    session.flush()
    event = emit(
        session,
        "approval.requested",
        document_type="ApprovalRequest",
        document_id=pending.id,
        number=pending.document_number,
        status="pending",
        summary=(
            f"Approval requested for {tool.name}"
            + (" (duplicate submission joined the pending request)" if deduplicated else "")
        ),
        actor_id=actor.id,
        receipt_id=receipt.id,
        extra={
            "approval_request_id": pending.id,
            "for_document_id": pending.document_id,
            "deduplicated": deduplicated,
        },
    )
    next_step = {
        "goods_acceptance": "a human counts the delivery and calls accept_goods (or reject_goods) with this request id",
        "invoice_variance": "a human reviews the variance: correct the invoice and post again, or reject_approval",
    }.get(
        kind,
        "a human approver decides via the approval inbox; then commit again with a new idempotency_key",
    )
    err = AnerpError(
        error_code,
        "; ".join(policy.reasons) or "approval required",
        {
            "policy": policy.as_dict(),
            "approval_request_id": pending.id,
            "approval_kind": kind,
            "approval_request_status": pending.status,
            "deduplicated": deduplicated,
            "receipt_id": receipt.id,
            "projected_effects": _projection_dict(projection, committed=False),
            "next_step": next_step,
        },
    )
    response = _jsonable(
        _error_response(
            err,
            mode="commit",
            request_id=request_id,
            extra={
                "events_emitted": [{"seq": event.seq, "type": event.type}],
                "receipt": receipt_to_dict(receipt),
            },
        )
    )
    idempotency.store(session, envelope.idempotency_key, tool.name, req_hash, response, receipt.id)
    session.commit()
    _log(
        {
            **base_log,
            "outcome": "error",
            "error_code": err.code.value,
            "error_message": err.message,
            "policy_decision": policy.decision,
            "policy": policy.as_dict(),
            "latency_ms": timer.ms,
            "document_id": pending.id,
            "receipt_id": receipt.id,
        }
    )
    return response
