"""Mount the A2A JSON-RPC endpoint and Agent Card on the FastAPI app."""

from __future__ import annotations

from typing import Any

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore

from anerp.a2a_agent.agent import AnerpAgentExecutor
from anerp.a2a_agent.card import build_card
from anerp.config import get_settings


def mount_a2a(app: Any) -> None:
    card = build_card(get_settings().public_url)
    handler = DefaultRequestHandler(
        agent_executor=AnerpAgentExecutor(), task_store=InMemoryTaskStore(), agent_card=card
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card, card_url="/.well-known/agent-card.json"),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
    )
    app.state.a2a_handler = handler
