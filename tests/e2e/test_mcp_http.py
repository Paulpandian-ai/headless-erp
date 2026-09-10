"""The MCP surface over streamable HTTP (in-process ASGI): auth, tools/list, tools/call, resources, prompts."""

from __future__ import annotations

import json

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from anerp.admin.tokens import bootstrap_admin
from anerp.core.dispatch import dispatch
from anerp.core.envelope import Envelope
from anerp.server import create_app
from tests.conftest import ADMIN, HUMAN

BOOT = "anerp_test_bootstrap_admin_token"


@pytest.fixture
def app(kernel):
    bootstrap_admin(kernel)
    kernel.commit()
    minted = dispatch(
        Envelope(
            tool="mint_token",
            mode="commit",
            idempotency_key="mcp-agent-token-1",
            actor=ADMIN,
            payload={
                "subject": "agent:mcp-test",
                "kind": "agent",
                "scopes": [
                    "procurement:write",
                    "procurement:receive",
                    "finance:ap:write",
                    "finance:ap:pay",
                    "*:read",
                ],
            },
        )
    )
    application = create_app()
    application.state.agent_token = minted["secret"]["token"]
    return application


async def _session(app, token):
    transport = httpx2.ASGITransport(app=app)
    http = httpx2.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    return http


@pytest.mark.anyio
async def test_unauthenticated_is_401(app):
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as http:
            r = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
            assert r.headers["www-authenticate"] == "Bearer"
            h = await http.get("/healthz")
            assert h.status_code == 200 and h.json()["status"] == "ok"
            keys = await http.get("/.well-known/anerp-keys.json")
            assert keys.json()["keys"][0]["active"]
            card = await http.get("/.well-known/agent-card.json")
            assert card.status_code == 200 and card.json()["name"] == "anerp-finance-agent"
            assert {s["id"] for s in card.json()["skills"]} == {
                "procure-to-pay",
                "order-to-cash",
                "period-close",
                "explain-balance",
            }


@pytest.mark.anyio
async def test_mcp_p2p_over_http(app):
    token = app.state.agent_token
    async with app.router.lifespan_context(app):
        http = await _session(app, token)
        async with (
            http,
            streamable_http_client("http://testserver/mcp", http_client=http) as (read, write),
            ClientSession(read, write) as session,
        ):
            init = await session.initialize()
            assert init.server_info.name == "anerp"
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {
                "create_purchase_order",
                "receive_goods",
                "post_supplier_invoice",
                "pay_supplier",
                "get_document",
                "trace_document",
                "mint_token",
            } <= names
            po_tool = next(t for t in tools.tools if t.name == "create_purchase_order")
            assert po_tool.input_schema["properties"]["mode"]["enum"] == ["simulate", "commit"]
            assert "Compensating tool: cancel_purchase_order" in (po_tool.description or "")
            assert (
                po_tool.annotations.read_only_hint is False
                and po_tool.annotations.idempotent_hint is True
            )
            assert (
                next(t for t in tools.tools if t.name == "get_document").annotations.read_only_hint
                is True
            )

            sim = await session.call_tool(
                "create_purchase_order",
                {
                    "supplier": "ACME",
                    "lines": [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
                },
            )
            body = sim.structured_content
            assert (
                body["ok"] and body["mode"] == "simulate" and body["policy"]["decision"] == "allow"
            )
            commit = await session.call_tool(
                "create_purchase_order",
                {
                    "mode": "commit",
                    "idempotency_key": "http-p2p-po-1",
                    "simulation_id": body["simulation_id"],
                    "supplier": "ACME",
                    "lines": [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
                },
            )
            po = commit.structured_content
            assert (
                po["ok"]
                and po["status"] == "applied"
                and po["receipt"]["actor_id"] == "agent:mcp-test"
            )
            number = po["document"]["number"]
            parked = (
                await session.call_tool(
                    "receive_goods",
                    {"mode": "commit", "idempotency_key": "http-p2p-grn-1", "po": number},
                )
            ).structured_content
            assert (
                not parked["ok"]
                and parked["error"]["details"]["approval_kind"] == "goods_acceptance"
            )
            accepted = dispatch(
                Envelope(
                    tool="accept_goods",
                    mode="commit",
                    idempotency_key="http-p2p-accept-1",
                    actor=HUMAN,
                    payload={
                        "request_id": parked["error"]["details"]["approval_request_id"],
                        "comment": "counted",
                    },
                )
            )
            assert accepted["ok"], accepted
            sinv = (
                await session.call_tool(
                    "post_supplier_invoice",
                    {
                        "mode": "commit",
                        "idempotency_key": "http-p2p-sinv-1",
                        "po": number,
                        "supplier_reference": "H1",
                        "lines": [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
                    },
                )
            ).structured_content
            assert sinv["ok"]
            pay = (
                await session.call_tool(
                    "pay_supplier",
                    {
                        "mode": "commit",
                        "idempotency_key": "http-p2p-pay-1",
                        "invoice": sinv["document"]["number"],
                    },
                )
            ).structured_content
            assert pay["ok"]
            replay = (
                await session.call_tool(
                    "pay_supplier",
                    {
                        "mode": "commit",
                        "idempotency_key": "http-p2p-pay-1",
                        "invoice": sinv["document"]["number"],
                    },
                )
            ).structured_content
            assert replay["status"] == "replayed"
            forbidden = await session.call_tool("approve_purchase_order", {"po": number})
            assert (
                forbidden.is_error and forbidden.structured_content["error"]["code"] == "FORBIDDEN"
            )
            tb = (await session.call_tool("get_trial_balance", {})).structured_content
            assert tb["result"]["is_balanced"]
            trace = (
                await session.call_tool("trace_document", {"id_or_number": number})
            ).structured_content
            assert [n["type"] for n in trace["result"]["nodes"]] == [
                "PurchaseOrder",
                "ApprovalRequest",
                "GoodsReceipt",
                "SupplierInvoice",
                "SupplierPayment",
            ]

            resources = await session.list_resources()
            assert {str(r.uri) for r in resources.resources} == {
                "anerp://chart-of-accounts",
                "anerp://policies",
                "anerp://capabilities",
                "anerp://events/latest",
            }
            coa = await session.read_resource("anerp://chart-of-accounts")
            assert json.loads(coa.contents[0].text)[0]["code"] == "1000"
            events = await session.read_resource("anerp://events/latest")
            assert any(
                e["type"] == "supplier_payment.recorded"
                for e in json.loads(events.contents[0].text)
            )
            prompts = await session.list_prompts()
            assert {p.name for p in prompts.prompts} == {
                "procure_to_pay_playbook",
                "order_to_cash_playbook",
                "period_close_checklist",
            }
            prompt = await session.get_prompt("procure_to_pay_playbook")
            assert "simulate" in prompt.messages[0].content.text


@pytest.mark.anyio
async def test_events_stream(app):
    token = app.state.agent_token
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {token}"},
        ) as http:
            r = await http.get(
                "/events/stream",
                params={"after_seq": 0, "types": "purchase_order.created", "max_events": 1},
            )
            assert r.status_code == 200
            lines = [line for line in r.text.splitlines() if line.startswith("data:")]
            got = json.loads(lines[0][5:])
            assert got["type"] == "purchase_order.created" and got["seq"] > 0
            denied = await http.get(
                "/events/stream", params={"max_events": 1}, headers={"Authorization": "Bearer nope"}
            )
            assert denied.status_code == 401
