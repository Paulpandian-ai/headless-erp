"""Admin tools (DESIGN.md §7.8): a scoped role, receipted like everything else."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlmodel import col, select

from anerp.admin.tokens import generate_token, hash_token
from anerp.core.context import ToolContext
from anerp.core.envelope import scope_subset
from anerp.core.errors import AnerpError, ErrorCode, precondition, validation
from anerp.core.ids import iso, utcnow
from anerp.core.projection import DocumentEffect, EventSpec, Projection
from anerp.core.registry import AdminTool, Annotations, QueryTool, tool
from anerp.events.log import latest_seq
from anerp.ledger.models import ApiToken, PolicyVersion, ServerKey
from anerp.ledger.receipts import generate_private_key_pem, keyring, public_pem
from anerp.policy.engine import get_engine
from anerp.policy.loader import parse_policy_yaml


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- tokens ------------------------------------------------------------------------
class MintTokenPayload(_Strict):
    subject: str = Field(
        min_length=1,
        max_length=128,
        description="Who the token identifies, e.g. agent:openai-procurement-1 or human:alice",
    )
    kind: Literal["agent", "human", "admin"]
    scopes: list[str] = Field(
        min_length=1, description="e.g. ['procurement:write', 'finance:ap:write', '*:read']"
    )
    expires_at: datetime | None = None


@tool
class MintToken(AdminTool):
    name = "mint_token"
    module = "admin"
    scope = "admin:tokens"
    purpose = "Create an API token for an agent, human or admin. The clear token is returned exactly once."
    preconditions = [
        "requested scopes are a subset of the caller's scopes",
        "admin:* can only be minted by admin:*",
    ]
    effects = "ApiToken row (hash only) created; events: token.minted. Response carries the clear token under `secret.token`."
    compensating_tool = "revoke_token"
    compensating_when = "any time"
    emits = ["token.minted"]
    payload_model = MintTokenPayload

    def project(self, ctx: ToolContext, payload: MintTokenPayload) -> Projection:
        caller_scopes = ctx.principal.scopes if ctx.principal else ["admin:*"]
        if not scope_subset(payload.scopes, caller_scopes):
            raise AnerpError(
                ErrorCode.FORBIDDEN,
                "requested scopes exceed the caller's scopes",
                {"requested": payload.scopes, "caller": caller_scopes},
            )
        if any(s.startswith("admin") for s in payload.scopes) and not any(
            s in ("admin:*", "*") for s in caller_scopes
        ):
            raise AnerpError(ErrorCode.FORBIDDEN, "admin scopes can only be minted by admin:*", {})
        if payload.kind == "admin" and "admin:*" not in payload.scopes:
            raise validation("kind=admin tokens must carry scope admin:*")
        clear = generate_token()
        row = ApiToken(
            token_hash=hash_token(clear),
            subject=payload.subject,
            kind=payload.kind,
            scopes=payload.scopes,
            created_by=ctx.actor.id,
            expires_at=payload.expires_at,
        )
        p = Projection()
        p.create("ApiToken", row, primary=True)
        p.secret = {"token": clear, "token_id": row.id}
        p.facts = {"token": {"kind": payload.kind, "scopes": payload.scopes}}
        p.events.append(
            EventSpec(
                "token.minted",
                f"Token minted for {payload.subject} ({payload.kind}) with scopes {payload.scopes}",
                "ApiToken",
                row,
            )
        )
        return p


class RevokeTokenPayload(_Strict):
    token_id: str = Field(description="Token id (from list_tokens) or subject")
    reason: str = Field(min_length=1)


@tool
class RevokeToken(AdminTool):
    name = "revoke_token"
    module = "admin"
    scope = "admin:tokens"
    purpose = "Revoke an API token; takes effect on the next request."
    preconditions = ["token exists and is not already revoked"]
    effects = "ApiToken.revoked_at set; events: token.revoked."
    compensating_tool = "mint_token"
    compensating_when = "mint a replacement; revocation itself is permanent"
    emits = ["token.revoked"]
    payload_model = RevokeTokenPayload
    annotations = Annotations(destructive=True)

    def project(self, ctx: ToolContext, payload: RevokeTokenPayload) -> Projection:
        row = (
            ctx.session.get(ApiToken, payload.token_id)
            or ctx.session.exec(
                select(ApiToken).where(
                    ApiToken.subject == payload.token_id, ApiToken.revoked_at.is_(None)
                )
            ).first()
        )  # type: ignore[union-attr]
        if row is None:
            from anerp.core.errors import not_found

            raise not_found("ApiToken", payload.token_id)
        ctx.touch(row)
        ctx.require(row.revoked_at is None, f"token {row.id} is already revoked")
        p = Projection()
        p.update(
            "ApiToken", row, {"revoked_at": ctx.now, "revoked_reason": payload.reason}, primary=True
        )
        p.facts = {"token": {"subject": row.subject}}
        p.events.append(
            EventSpec(
                "token.revoked",
                f"Token {row.id} for {row.subject} revoked: {payload.reason}",
                "ApiToken",
                row,
            )
        )
        return p


class EmptyPayload(_Strict):
    pass


@tool
class ListTokens(QueryTool):
    name = "list_tokens"
    module = "admin"
    scope = "admin:tokens"
    purpose = "List API tokens: subject, kind, scopes, expiry, revocation and last use. Hashes are never returned."
    payload_model = EmptyPayload

    def run(self, ctx: ToolContext, payload: EmptyPayload) -> dict[str, Any]:
        rows = ctx.session.exec(select(ApiToken).order_by(ApiToken.created_at)).all()  # type: ignore[arg-type]
        return {
            "tokens": [
                {
                    "id": r.id,
                    "subject": r.subject,
                    "kind": r.kind,
                    "scopes": r.scopes,
                    "created_by": r.created_by,
                    "created_at": iso(r.created_at),
                    "expires_at": iso(r.expires_at),
                    "revoked_at": iso(r.revoked_at),
                    "last_used_at": iso(r.last_used_at),
                }
                for r in rows
            ],
            "count": len(rows),
        }


# ---- policy ------------------------------------------------------------------------
class UpdatePolicyPayload(_Strict):
    yaml: str = Field(min_length=1, description="Full policy set YAML (replaces the active set)")
    comment: str = Field(min_length=1)


@tool
class UpdatePolicy(AdminTool):
    name = "update_policy"
    module = "admin"
    scope = "admin:policy"
    purpose = "Validate and activate a new policy set; prior versions are kept."
    preconditions = ["YAML parses and every rule condition compiles"]
    effects = "PolicyVersion row created and activated (engine hot-swapped after commit); receipt records before/after policy hash; events: policy.updated."
    compensating_tool = "update_policy"
    compensating_when = "re-submit the previous YAML (kept in policy_version)"
    emits = ["policy.updated"]
    payload_model = UpdatePolicyPayload

    def project(self, ctx: ToolContext, payload: UpdatePolicyPayload) -> Projection:
        try:
            parsed = parse_policy_yaml(payload.yaml)
        except Exception as exc:  # noqa: BLE001
            raise validation(f"policy YAML invalid: {exc}") from exc
        engine = get_engine()
        from anerp.core.hashing import sha256_hex

        latest = ctx.session.exec(
            select(PolicyVersion).order_by(PolicyVersion.version.desc())
        ).first()  # type: ignore[attr-defined]
        version = (latest.version + 1) if latest else 1
        row = PolicyVersion(
            version=version,
            yaml_text=payload.yaml,
            policy_hash=sha256_hex(payload.yaml),
            comment=payload.comment,
            updated_by=ctx.actor.id,
        )
        p = Projection()
        for old in ctx.session.exec(
            select(PolicyVersion).where(col(PolicyVersion.is_active).is_(True))
        ).all():
            ctx.touch(old)
            p.update("PolicyVersion", old, {"is_active": False})
        p.create("PolicyVersion", row, primary=True)
        p.facts = {
            "policy": {
                "before_hash": engine.policy_hash,
                "after_hash": row.policy_hash,
                "rules": len(parsed.rules),
            }
        }
        p.extra = {
            "before_hash": engine.policy_hash,
            "after_hash": row.policy_hash,
            "rule_ids": [r.id for r in parsed.rules],
        }
        p.events.append(
            EventSpec(
                "policy.updated",
                f"Policy v{version} activated by {ctx.actor.id}: {payload.comment}",
                "PolicyVersion",
                row,
                {"policy_hash": row.policy_hash},
            )
        )
        yaml_text = payload.yaml
        p.after_commit = lambda: engine.replace(yaml_text)
        return p


# ---- keys ---------------------------------------------------------------------------
class RotateKeyPayload(_Strict):
    reason: str = Field(min_length=1)


@tool
class RotateSigningKey(AdminTool):
    name = "rotate_signing_key"
    module = "admin"
    scope = "admin:keys"
    purpose = "Generate a new Ed25519 receipt-signing key; the previous key is retired but kept for verification."
    preconditions = ["caller has admin:keys"]
    effects = "New ServerKey active, old key retired_at set; this operation's own receipt is signed with the new key; events: key.rotated."
    compensating_tool = None
    emits = ["key.rotated"]
    payload_model = RotateKeyPayload

    def project(self, ctx: ToolContext, payload: RotateKeyPayload) -> Projection:
        p = Projection()
        for old in ctx.session.exec(select(ServerKey).where(ServerKey.retired_at.is_(None))).all():  # type: ignore[union-attr]
            ctx.touch(old)
            p.update("ServerKey", old, {"retired_at": ctx.now})
        private_pem = generate_private_key_pem()
        new_key = ServerKey(public_key_pem=public_pem(private_pem), private_key_pem=private_pem)
        p.create("ServerKey", new_key, primary=True)
        p.facts = {"key": {"rotation": True}}
        p.extra = {"new_public_key_pem": new_key.public_key_pem}
        p.events.append(
            EventSpec(
                "key.rotated",
                f"Signing key rotated by {ctx.actor.id}: {payload.reason}",
                "ServerKey",
                new_key,
            )
        )
        p.after_commit = keyring.reset
        return p


# ---- reset --------------------------------------------------------------------------
class ResetPayload(_Strict):
    fixture_name: Literal["baseline", "empty"] = "baseline"
    confirm: Literal["RESET"] = Field(description="Must be the literal string RESET")


BUSINESS_TABLES = [  # children before parents (foreign keys)
    "journal_line",
    "journal_entry",
    "open_item",
    "supplier_payment",
    "supplier_invoice",
    "goods_receipt",
    "purchase_order_line",
    "purchase_order",
    "customer_payment",
    "credit_note",
    "customer_invoice",
    "shipment",
    "sales_order_line",
    "sales_order",
    "approval_request",
    "event",
    "receipt",
    "idempotency_record",
    "document_sequence",
    "item",
    "supplier",
    "customer",
    "account",
    "fiscal_period",
]


@tool
class ResetAndSeed(AdminTool):
    name = "reset_and_seed"
    module = "admin"
    scope = "admin:reset"
    purpose = "DEV ONLY: drop all business data and reseed a named fixture. Refuses unless ANERP_ENV is dev or test."
    preconditions = ["ANERP_ENV in (dev, test)", "confirm == 'RESET'"]
    effects = "All business tables, events, receipts and idempotency records are cleared; tokens, keys and policy versions are kept; fixture reseeded through the dispatcher; events: system.reset."
    compensating_tool = None
    emits = ["system.reset"]
    payload_model = ResetPayload
    annotations = Annotations(destructive=True, idempotent=False)

    def project(self, ctx: ToolContext, payload: ResetPayload) -> Projection:
        if ctx.settings.env not in ("dev", "test"):
            raise precondition(
                f"reset_and_seed is disabled in ANERP_ENV={ctx.settings.env}", env=ctx.settings.env
            )
        p = Projection()
        p.facts = {"reset": {"fixture": payload.fixture_name}}
        fixture = payload.fixture_name
        actor = ctx.actor

        def apply(session: Any) -> dict[str, Any]:
            from anerp.core.requestlog import request_log, simulations
            from anerp.seed import seed_fixture

            for table in BUSINESS_TABLES:
                session.execute(text(f"DELETE FROM {table}"))
            session.flush()
            request_log.clear()
            simulations.clear()
            counts = seed_fixture(session, fixture, actor_id=actor.id)
            return {"fixture": fixture, "seeded": counts}

        p.apply_hook = apply
        p.events.append(
            EventSpec(
                "system.reset",
                f"Database reset and reseeded with fixture '{fixture}' by {actor.id}",
                "System",
            )
        )
        return p


# ---- status ---------------------------------------------------------------------------
@tool
class GetSystemStatus(QueryTool):
    name = "get_system_status"
    module = "admin"
    scope = "admin:status"
    purpose = "DB reachability, migration head, active signing key, policy version, latest event seq, token counts."
    payload_model = EmptyPayload

    def run(self, ctx: ToolContext, payload: EmptyPayload) -> dict[str, Any]:
        return system_status(ctx.session)


def system_status(session: Any) -> dict[str, Any]:
    from anerp.config import get_settings

    engine = get_engine()
    active_key = keyring.ensure_active(session)
    tokens = session.exec(select(ApiToken)).all()
    try:
        head = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        session.rollback()
        head = None
    return {
        "env": get_settings().env,
        "database": {
            "reachable": True,
            "dialect": session.get_bind().dialect.name,
            "migration_head": head,
        },
        "signing_key": {"id": active_key.id, "created_at": iso(active_key.created_at)},
        "policy": {
            "version": engine.policy.version,
            "hash": engine.policy_hash,
            "rules": len(engine.policy.rules),
        },
        "events": {"latest_seq": latest_seq(session)},
        "tokens": {
            "total": len(tokens),
            "active": sum(1 for t in tokens if t.revoked_at is None),
            "admin": sum(1 for t in tokens if t.kind == "admin" and t.revoked_at is None),
        },
        "time": iso(utcnow()),
    }


__all__ = ["DocumentEffect", "system_status"]
