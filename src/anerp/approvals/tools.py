"""Approval inbox tools (DESIGN.md §7.9). approve_purchase_order lives in procurement."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from anerp.approvals.models import ApprovalRequest
from anerp.core.context import ToolContext
from anerp.core.ids import iso, utcnow
from anerp.core.projection import EventSpec, Projection
from anerp.core.registry import Annotations, QueryTool, WriteTool, tool
from anerp.models import DOCUMENT_TYPES


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def approval_to_dict(r: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": r.id,
        "kind": r.kind,
        "document_type": r.document_type,
        "document_id": r.document_id,
        "document_number": r.document_number,
        "tool_name": r.tool_name,
        "requested_by": r.requested_by,
        "reason": r.reason,
        "status": r.status,
        "decided_by": r.decided_by,
        "decided_at": iso(r.decided_at),
        "decision_comment": r.decision_comment,
        "expires_at": iso(r.expires_at),
        "created_at": iso(r.created_at),
        "projected_effects": r.projected_effects_json,
        "payload": r.payload_json,
    }


class ListPendingPayload(_Strict):
    for_actor: str | None = Field(default=None, description="Filter by the requesting actor id")
    kind: Literal["po_approval", "goods_acceptance", "invoice_variance"] | None = Field(
        default=None, description="Filter by request kind"
    )
    limit: int = Field(default=50, ge=1, le=500)


@tool
class ListPendingApprovals(QueryTool):
    name = "list_pending_approvals"
    module = "approvals"
    scope = "approvals:read"
    purpose = "List pending approval requests with projected effects and requester, oldest first."
    payload_model = ListPendingPayload

    def run(self, ctx: ToolContext, payload: ListPendingPayload) -> dict[str, Any]:
        now = utcnow()
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending")
            .order_by(ApprovalRequest.created_at)
        )  # type: ignore[arg-type]
        if payload.for_actor:
            stmt = stmt.where(ApprovalRequest.requested_by == payload.for_actor)
        if payload.kind:
            stmt = stmt.where(ApprovalRequest.kind == payload.kind)
        rows = ctx.session.exec(stmt.limit(payload.limit)).all()
        items = []
        for r in rows:
            d = approval_to_dict(r)
            d["expired"] = bool(
                r.expires_at and r.expires_at.replace(tzinfo=None) < now.replace(tzinfo=None)
            )
            items.append(d)
        return {"pending": items, "count": len(items)}


class RequestApprovalPayload(_Strict):
    kind: Literal["po_approval", "goods_acceptance", "invoice_variance"] = "po_approval"
    document_type: str = Field(description="e.g. PurchaseOrder")
    document_id: str = Field(description="Document number or id")
    reason: str = Field(min_length=1)


@tool
class RequestApproval(WriteTool):
    name = "request_approval"
    module = "approvals"
    scope = "approvals:write"
    purpose = "Explicitly ask a human to approve a document (the dispatcher also does this automatically on REQUIRES_APPROVAL)."
    preconditions = ["document exists", "no pending request already exists for it"]
    effects = "ApprovalRequest created (pending, expires after ANERP_APPROVAL_TTL_HOURS); events: approval.requested."
    compensating_tool = "reject_approval"
    compensating_when = "to withdraw the request"
    emits = ["approval.requested"]
    payload_model = RequestApprovalPayload

    def project(self, ctx: ToolContext, payload: RequestApprovalPayload) -> Projection:
        from datetime import timedelta

        model = DOCUMENT_TYPES.get(payload.document_type)
        if model is None:
            from anerp.core.errors import validation

            raise validation(
                f"unknown document type {payload.document_type}", known=sorted(DOCUMENT_TYPES)
            )
        doc = ctx.get_by_ref(model, payload.document_id, payload.document_type)
        existing = [r for r in ctx.find(ApprovalRequest, document_id=doc.id, status="pending")]
        ctx.require(
            not existing,
            f"a pending approval request {existing[0].id if existing else ''} already exists",
            existing_id=existing[0].id if existing else None,
        )
        req = ApprovalRequest(
            kind=payload.kind,
            document_type=payload.document_type,
            document_id=doc.id,
            document_number=getattr(doc, "number", None),
            tool_name=self.name,
            requested_by=ctx.actor.id,
            reason=payload.reason,
            projected_effects_json={
                "document": {
                    "type": payload.document_type,
                    "id": doc.id,
                    "number": getattr(doc, "number", None),
                    "status": getattr(doc, "status", None),
                }
            },
            expires_at=ctx.now + timedelta(hours=ctx.settings.approval_ttl_hours),
        )
        p = Projection()
        p.create("ApprovalRequest", req, primary=True)
        p.facts = {"approval": {"document_type": payload.document_type}}
        p.events.append(
            EventSpec(
                "approval.requested",
                f"Approval requested for {payload.document_type} {req.document_number or doc.id}: {payload.reason}",
                "ApprovalRequest",
                req,
                {"approval_request_id": req.id, "for_document_id": doc.id},
            )
        )
        return p


class RejectApprovalPayload(_Strict):
    request_id: str
    reason: str = Field(min_length=1)


@tool
class RejectApproval(WriteTool):
    name = "reject_approval"
    module = "approvals"
    scope = "procurement:approve"
    purpose = "Reject a pending approval request of any kind (human approvers only); the originating agent sees it via events."
    preconditions = ["request status pending", "actor token kind is human or admin"]
    effects = "ApprovalRequest -> rejected; a draft PurchaseOrder stays draft (cancel it separately); a parked invoice_variance is closed; events: approval.rejected."
    compensating_tool = None
    common_errors = ["PRECONDITION_FAILED when not pending", "POLICY_DENIED for agent tokens"]
    emits = ["approval.rejected"]
    payload_model = RejectApprovalPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: RejectApprovalPayload) -> Projection:
        req = ctx.get(ApprovalRequest, payload.request_id, "ApprovalRequest")
        ctx.require(req.status == "pending", f"request {req.id} is {req.status}", status=req.status)
        p = Projection()
        p.update(
            "ApprovalRequest",
            req,
            {
                "status": "rejected",
                "decided_by": ctx.actor.id,
                "decided_at": ctx.now,
                "decision_comment": payload.reason,
            },
            primary=True,
        )
        p.facts = {
            "approval": {"document_type": req.document_type, "requested_by": req.requested_by}
        }
        p.events.append(
            EventSpec(
                "approval.rejected",
                f"Approval request {req.id} for {req.document_type} {req.document_number or req.document_id} rejected by {ctx.actor.id}: {payload.reason}",
                "ApprovalRequest",
                req,
                {
                    "approval_request_id": req.id,
                    "for_document_id": req.document_id,
                    "requested_by": req.requested_by,
                },
            )
        )
        return p
