from __future__ import annotations

from anerp.admin.tokens import bootstrap_admin, resolve_token
from anerp.core.dispatch import dispatch, run_query
from anerp.core.envelope import Envelope, Principal
from tests.conftest import ADMIN, AGENT, Client


def test_bootstrap_and_mint_and_revoke(kernel, admin: Client) -> None:
    row = bootstrap_admin(kernel)
    kernel.commit()
    assert row is not None and row.subject == "admin:bootstrap"
    assert bootstrap_admin(kernel) is None
    principal = resolve_token(kernel, "anerp_test_bootstrap_admin_token")
    assert principal and principal.kind == "admin" and principal.has_scope("anything:write")
    assert resolve_token(kernel, "wrong") is None

    minted = dispatch(
        Envelope(
            tool="mint_token",
            mode="commit",
            idempotency_key="mint-0001",
            actor=ADMIN,
            payload={
                "subject": "agent:sdk-1",
                "kind": "agent",
                "scopes": ["procurement:write", "*:read"],
            },
        ),
        principal=principal,
    )
    assert minted["ok"] and minted["secret"]["token"].startswith("anerp_")
    replay = dispatch(
        Envelope(
            tool="mint_token",
            mode="commit",
            idempotency_key="mint-0001",
            actor=ADMIN,
            payload={
                "subject": "agent:sdk-1",
                "kind": "agent",
                "scopes": ["procurement:write", "*:read"],
            },
        ),
        principal=principal,
    )
    assert replay["status"] == "replayed" and "secret" not in replay
    agent_principal = resolve_token(kernel, minted["secret"]["token"])
    assert agent_principal and agent_principal.scopes == ["procurement:write", "*:read"]
    # scope escalation refused
    esc = dispatch(
        Envelope(
            tool="mint_token",
            mode="commit",
            idempotency_key="mint-0002",
            actor=AGENT,
            payload={"subject": "x", "kind": "agent", "scopes": ["admin:*"]},
        ),
        principal=agent_principal,
    )
    assert esc["error"]["code"] == "FORBIDDEN"
    tokens = run_query("list_tokens", {}, ADMIN, principal=principal)["result"]
    assert tokens["count"] == 2 and all("hash" not in t for t in tokens["tokens"])
    revoked = dispatch(
        Envelope(
            tool="revoke_token",
            mode="commit",
            idempotency_key="revoke-0001",
            actor=ADMIN,
            payload={"token_id": minted["secret"]["token_id"], "reason": "rotate"},
        ),
        principal=principal,
    )
    assert revoked["ok"]
    assert resolve_token(kernel, minted["secret"]["token"]) is None
    status = run_query("get_system_status", {}, ADMIN, principal=principal)["result"]
    assert status["tokens"]["active"] == 1 and status["events"]["latest_seq"] > 0


def test_rotate_signing_key_keeps_old_receipts_verifiable(
    kernel, admin: Client, agent: Client
) -> None:
    old = agent.ok("create_supplier", code="K1", name="k")
    rot = admin.ok("rotate_signing_key", reason="scheduled")
    assert rot["receipt"]["public_key_id"] == rot["document"]["id"]
    new = agent.ok("create_supplier", code="K2", name="k")
    assert new["receipt"]["public_key_id"] != old["receipt"]["public_key_id"]
    v_old = agent.query("verify_receipt", receipt_id=old["receipt"]["id"])
    assert v_old["valid"] and v_old["key_retired"]
    assert agent.query("verify_receipt", receipt_id=new["receipt"]["id"])["valid"]
    assert agent.query("verify_receipt", receipt_id=rot["receipt"]["id"])["valid"]


def test_reset_and_seed_dev_only(kernel, admin: Client, agent: Client, monkeypatch) -> None:
    agent.ok("create_supplier", code="TEMP", name="t")
    r = admin.ok("reset_and_seed", fixture_name="baseline", confirm="RESET")
    assert r["hook_result"]["fixture"] == "baseline"
    assert agent.query("search_documents", type="Supplier")["count"] == 2
    assert agent.query("get_trial_balance")["is_balanced"]
    from anerp.config import get_settings

    monkeypatch.setattr(get_settings(), "env", "demo")
    from anerp.core.envelope import local_principal

    denied = dispatch(
        Envelope(
            tool="reset_and_seed",
            mode="commit",
            idempotency_key="reset-demo-0001",
            actor=ADMIN,
            payload={"fixture_name": "baseline", "confirm": "RESET"},
        ),
        principal=local_principal("admin:ops"),
    )
    assert denied["error"]["code"] == "PRECONDITION_FAILED"
    unauthenticated = admin.commit("reset_and_seed", fixture_name="baseline", confirm="RESET")
    assert unauthenticated["error"]["code"] == "UNAUTHORIZED"


def test_principal_scope_matching() -> None:
    p = Principal(subject="s", kind="agent", scopes=["finance:*", "*:read", "procurement:write"])
    assert (
        p.has_scope("finance:ap:write")
        and p.has_scope("inventory:read")
        and p.has_scope("procurement:write")
    )
    assert not p.has_scope("procurement:approve") and not p.has_scope("admin:tokens")
