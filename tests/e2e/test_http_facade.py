"""The HTTP facade at /api: auth, scopes, simulate/commit parity with MCP, errors, CORS, OpenAPI."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

from anerp.admin.tokens import bootstrap_admin
from anerp.core.dispatch import dispatch
from anerp.core.envelope import Envelope
from anerp.mcp_server.registry import call_tool
from anerp.server import create_app
from tests.conftest import ADMIN

AGENT_SCOPES = ["procurement:write", "finance:ap:write", "finance:ap:pay", "*:read"]


def _mint(session: Any, subject: str, scopes: list[str], key: str) -> str:
    minted = dispatch(
        Envelope(
            tool="mint_token",
            mode="commit",
            idempotency_key=key,
            actor=ADMIN,
            payload={"subject": subject, "kind": "agent", "scopes": scopes},
        )
    )
    assert minted["ok"], minted
    return str(minted["secret"]["token"])


@pytest.fixture
def app(kernel):
    bootstrap_admin(kernel)
    kernel.commit()
    application = create_app()
    application.state.agent_token = _mint(kernel, "agent:facade", AGENT_SCOPES, "facade-agent-1")
    application.state.reader_token = _mint(kernel, "agent:reader", ["*:read"], "facade-reader-1")
    return application


def _client(app, token: str | None = None) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )


@pytest.mark.anyio
async def test_unauthenticated_and_bad_token_are_401(app):
    async with app.router.lifespan_context(app):
        async with _client(app) as http:
            r = await http.post("/api/query/get_trial_balance", json={})
            assert r.status_code == 401
            assert r.json()["error"]["code"] == "UNAUTHORIZED"
            # No token at all advertises the scheme, exactly as the MCP transport does.
            assert r.headers["www-authenticate"] == "Bearer"

        async with _client(app, "nope") as http:
            bad = await http.post("/api/query/get_trial_balance", json={})
            assert bad.status_code == 401
            assert bad.json()["error"]["code"] == "UNAUTHORIZED"
            # A token that was sent but did not resolve is not a challenge to re-authenticate.
            assert "www-authenticate" not in bad.headers


@pytest.mark.anyio
async def test_a_401_is_shaped_like_every_other_error_and_is_explainable(app):
    """A rejected token gets the same envelope as a POLICY_DENIED, request_id included, and the
    id resolves through explain_error once the caller holds a working token."""
    async with app.router.lifespan_context(app):
        async with _client(app, "nope") as http:
            body = (await http.post("/api/query/get_trial_balance", json={})).json()

        assert body["ok"] is False and body["mode"] == "query"
        assert body["error"]["code"] == "UNAUTHORIZED"
        assert body["error"]["retry_advice"] and body["error"]["details"] == {}
        request_id = body["request_id"]
        assert request_id

        async with _client(app, app.state.agent_token) as http:
            explained = (
                await http.post("/api/query/explain_error", json={"request_id": request_id})
            ).json()

    assert explained["ok"], explained
    entry = explained["result"]
    assert entry["error_code"] == "UNAUTHORIZED"
    # The log knows which tool the caller was reaching for, not just that someone was refused.
    assert entry["tool"] == "get_trial_balance" and entry["mode"] == "query"
    assert "UNAUTHORIZED" in entry["explanation"]


@pytest.mark.anyio
async def test_whoami_answers_for_any_authenticated_token(app, kernel):
    """A token with no read scope at all cannot call list_capabilities, but it can always ask
    what it is and what it may call."""
    narrow = _mint(kernel, "agent:narrow", ["procurement:write"], "facade-narrow-1")
    async with app.router.lifespan_context(app), _client(app, narrow) as http:
        refused = (await http.post("/api/query/list_capabilities", json={})).json()
        assert refused["error"]["code"] == "FORBIDDEN"
        me = (await http.post("/api/query/whoami", json={})).json()
    assert me["ok"], me
    result = me["result"]
    assert result["subject"] == "agent:narrow" and result["kind"] == "agent"
    assert result["scopes"] == ["procurement:write"] and result["expires_at"] is None
    assert "create_purchase_order" in result["tools"] and "whoami" in result["tools"]
    assert "list_capabilities" not in result["tools"]


@pytest.mark.anyio
async def test_every_401_carries_a_distinct_request_id(app):
    async with app.router.lifespan_context(app), _client(app, "nope") as http:
        ids = {
            (await http.post("/api/query/get_trial_balance", json={})).json()["request_id"]
            for _ in range(3)
        }
    assert len(ids) == 3


@pytest.mark.anyio
async def test_query_matches_call_tool_exactly(app):
    """The facade adds nothing: same arguments in, same JSON out (request_id is per-call)."""
    token = app.state.agent_token
    async with app.router.lifespan_context(app), _client(app, token) as http:
        r = await http.post("/api/query/get_trial_balance", json={"period_code": "2026-09"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] and body["result"]["is_balanced"]
        assert r.headers["x-request-id"]

    from anerp.mcp_server.auth import principal_from_token

    principal = principal_from_token(token)
    direct = call_tool("get_trial_balance", {"period_code": "2026-09"}, principal)
    assert body.get("request_id") != direct.get("request_id")
    assert {k: v for k, v in body.items() if k != "request_id"} == {
        k: v for k, v in json.loads(json.dumps(direct, default=str)).items() if k != "request_id"
    }


@pytest.mark.anyio
async def test_empty_body_is_an_empty_payload(app):
    async with app.router.lifespan_context(app), _client(app, app.state.agent_token) as http:
        r = await http.post("/api/query/list_capabilities", content=b"")
        assert r.status_code == 200 and r.json()["ok"]
        assert r.json()["result"]["count"] > 0


@pytest.mark.anyio
async def test_simulate_then_commit_then_replay(app):
    token = app.state.agent_token
    payload = {
        "supplier": "ACME",
        "lines": [{"sku": "HOSE-10M", "qty": 5, "unit_cost": "25.00"}],
    }

    async def po_count(http) -> int:
        r = await http.post("/api/query/search_documents", json={"type": "PurchaseOrder"})
        return int(r.json()["result"]["count"])

    async with app.router.lifespan_context(app), _client(app, token) as http:
        before = await po_count(http)

        sim = (await http.post("/api/simulate/create_purchase_order", json=payload)).json()
        assert sim["ok"] and sim["mode"] == "simulate"
        assert sim["policy"]["decision"] == "allow"
        assert sim["projected_effects"]["documents"][0]["number"].endswith("(projected)")
        assert "receipt" not in sim

        # Simulate is provably zero-write: the document count is unchanged.
        assert await po_count(http) == before

        body = {**payload, "idempotency_key": "facade-po-commit-1"}
        first = (await http.post("/api/commit/create_purchase_order", json=body)).json()
        assert first["ok"] and first["status"] == "applied"
        assert first["receipt"]["tool_name"] == "create_purchase_order"
        number = first["document"]["number"]

        assert await po_count(http) == before + 1

        again = (await http.post("/api/commit/create_purchase_order", json=body)).json()
        assert again["status"] == "replayed"
        assert again["document"]["number"] == number
        assert await po_count(http) == before + 1

        conflict = (
            await http.post(
                "/api/commit/create_purchase_order",
                json={**body, "lines": [{"sku": "HOSE-10M", "qty": 9, "unit_cost": "25.00"}]},
            )
        ).json()
        assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.anyio
async def test_commit_without_idempotency_key_is_validation_error(app):
    async with app.router.lifespan_context(app), _client(app, app.state.agent_token) as http:
        r = await http.post(
            "/api/commit/create_purchase_order",
            json={"supplier": "ACME", "lines": []},
        )
        assert r.status_code == 200
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_validation_error_lists_expected_fields(app):
    async with app.router.lifespan_context(app), _client(app, app.state.agent_token) as http:
        write = (await http.post("/api/simulate/create_purchase_order", json={"wrong": 1})).json()
        assert write["error"]["code"] == "VALIDATION_ERROR"
        details = write["error"]["details"]
        assert "supplier" in details["expected_fields"]
        assert "lines" in details["required_fields"]
        assert "memo" in details["expected_fields"]
        assert "memo" not in details["required_fields"]

        read = (await http.post("/api/query/get_document", json={"wrong": 1})).json()
        assert read["error"]["code"] == "VALIDATION_ERROR"
        assert read["error"]["details"]["required_fields"] == ["id_or_number"]


@pytest.mark.anyio
async def test_scopes_are_the_mcp_scopes(app):
    """The facade checks no scopes itself; dispatch refuses the read-only token."""
    async with app.router.lifespan_context(app), _client(app, app.state.reader_token) as http:
        allowed = await http.post("/api/query/get_trial_balance", json={})
        assert allowed.json()["ok"]

        denied = (
            await http.post(
                "/api/simulate/create_purchase_order",
                json={"supplier": "ACME", "lines": []},
            )
        ).json()
        assert denied["ok"] is False
        assert denied["error"]["code"] == "FORBIDDEN"
        assert denied["error"]["details"]["required_scope"] == "procurement:write"


@pytest.mark.anyio
async def test_route_and_tool_kind_must_agree(app):
    async with app.router.lifespan_context(app), _client(app, app.state.agent_token) as http:
        wrong_way = (await http.post("/api/query/create_purchase_order", json={})).json()
        assert wrong_way["error"]["code"] == "VALIDATION_ERROR"
        assert "/api/simulate/create_purchase_order" in wrong_way["error"]["message"]

        other_way = (await http.post("/api/commit/get_trial_balance", json={})).json()
        assert other_way["error"]["code"] == "VALIDATION_ERROR"
        assert "/api/query/get_trial_balance" in other_way["error"]["message"]


@pytest.mark.anyio
async def test_body_mode_may_not_contradict_the_route(app):
    async with app.router.lifespan_context(app), _client(app, app.state.agent_token) as http:
        r = (
            await http.post(
                "/api/simulate/create_purchase_order",
                json={"supplier": "ACME", "lines": [], "mode": "commit"},
            )
        ).json()
        assert r["error"]["code"] == "VALIDATION_ERROR"
        assert r["error"]["details"] == {"route_mode": "simulate", "body_mode": "commit"}


@pytest.mark.anyio
async def test_unknown_tool_and_malformed_body(app):
    async with app.router.lifespan_context(app), _client(app, app.state.agent_token) as http:
        unknown = (await http.post("/api/query/no_such_tool", json={})).json()
        assert unknown["error"]["code"] == "NOT_FOUND"

        bad = await http.post(
            "/api/simulate/create_purchase_order",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert bad.status_code == 200
        assert bad.json()["error"]["code"] == "VALIDATION_ERROR"

        not_object = await http.post("/api/query/get_trial_balance", json=[1, 2])
        assert not_object.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_cors_preflight_and_actual_request(app):
    """ANERP_CORS_ORIGINS is unset and ANERP_ENV=test, so the default is "*"."""
    async with app.router.lifespan_context(app):
        async with _client(app) as http:
            pre = await http.request(
                "OPTIONS",
                "/api/query/get_trial_balance",
                headers={
                    "Origin": "http://console.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert pre.status_code == 200
            assert pre.headers["access-control-allow-origin"] == "*"

        async with _client(app, app.state.agent_token) as http:
            r = await http.post(
                "/api/query/get_trial_balance",
                json={},
                headers={"Origin": "http://console.example"},
            )
            assert r.headers["access-control-allow-origin"] == "*"
            # Bearer auth only: credentials must stay off so "*" remains valid for browsers.
            assert "access-control-allow-credentials" not in r.headers


def test_facade_routes_are_in_the_openapi_schema(kernel):
    spec = create_app().openapi()
    for path in ("/api/query/{tool}", "/api/simulate/{tool}", "/api/commit/{tool}"):
        assert path in spec["paths"], path
        operation = spec["paths"][path]["post"]
        assert operation["summary"]
        assert operation["requestBody"]["content"]["application/json"]
        assert {"200", "401"} <= set(operation["responses"])
        assert operation["parameters"][0]["name"] == "tool"
