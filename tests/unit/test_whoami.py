"""`whoami`: what the calling token is and which tools it may call (DESIGN.md §7.5).

A client that holds a token can always answer "what can I do with this?" without provoking a
FORBIDDEN, and without needing `admin:tokens` to read its own row through `list_tokens`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from anerp.admin.tokens import resolve_token
from anerp.core.dispatch import dispatch, run_query
from anerp.core.envelope import Envelope, Principal, local_principal
from anerp.core.registry import registry
from tests.conftest import ADMIN, AGENT


def _mint(scopes: list[str], key: str, *, expires_at: datetime | None = None) -> str:
    payload = {"subject": "agent:who", "kind": "agent", "scopes": scopes}
    if expires_at is not None:
        payload["expires_at"] = expires_at.isoformat()
    minted = dispatch(
        Envelope(
            tool="mint_token", mode="commit", idempotency_key=key, actor=ADMIN, payload=payload
        )
    )
    assert minted["ok"], minted
    return str(minted["secret"]["token"])


def _whoami(principal: Principal) -> dict:
    r = run_query("whoami", {}, AGENT, principal=principal)
    assert r["ok"], r
    return r["result"]


def test_whoami_reports_the_token_and_only_the_tools_it_may_call(kernel) -> None:
    expiry = datetime(2030, 1, 1, tzinfo=UTC)
    principal = resolve_token(
        kernel, _mint(["procurement:write", "*:read"], "whoami-mint-1", expires_at=expiry)
    )
    assert principal is not None

    me = _whoami(principal)
    assert me["subject"] == "agent:who" and me["kind"] == "agent"
    assert me["scopes"] == ["procurement:write", "*:read"]
    assert me["token_id"] == principal.token_id
    assert me["expires_at"] == "2030-01-01T00:00:00Z"

    tools = me["tools"]
    assert tools == sorted(tools) and me["tool_count"] == len(tools)
    # Exactly the registry filtered by scope: every read tool and the procurement writes, none
    # of finance, sales or admin.
    assert set(tools) == {t.name for t in registry.all() if principal.has_scope(t.scope)}
    assert {"create_purchase_order", "get_trial_balance", "list_capabilities"} <= set(tools)
    assert not {
        "post_supplier_invoice",
        "ship_order",
        "mint_token",
        "approve_purchase_order",
    } & set(tools)


def test_whoami_needs_no_scope_and_always_lists_itself(kernel) -> None:
    # The narrowest token there is still reaches whoami, and whoami is the only tool it can call.
    principal = resolve_token(kernel, _mint(["nothing:here"], "whoami-mint-2"))
    assert principal is not None
    me = _whoami(principal)
    assert me["tools"] == ["whoami"] and me["tool_count"] == 1
    assert me["expires_at"] is None


def test_whoami_for_admin_is_the_whole_registry(kernel) -> None:
    me = _whoami(local_principal("admin:local"))
    assert me["subject"] == "admin:local" and me["kind"] == "admin"
    assert me["token_id"] is None and me["expires_at"] is None
    assert me["tools"] == sorted(t.name for t in registry.all())


def test_whoami_without_a_principal_is_unauthorized(kernel) -> None:
    # Only reachable in ANERP_ENV=test, where the dispatcher lets in-process calls through
    # without a principal; the tool still refuses to describe an actor it did not authenticate.
    r = run_query("whoami", {}, AGENT)
    assert not r["ok"] and r["error"]["code"] == "UNAUTHORIZED"
