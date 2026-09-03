"""MCP resources (DESIGN.md §11)."""

from __future__ import annotations

import json
from typing import Any

import mcp_types as types
from sqlmodel import select

from anerp.core.registry import registry
from anerp.db import session_scope
from anerp.events.log import event_to_dict
from anerp.events.models import Event
from anerp.masterdata.models import Account
from anerp.policy.engine import get_engine

RESOURCES: list[dict[str, str]] = [
    {
        "uri": "anerp://chart-of-accounts",
        "name": "chart_of_accounts",
        "description": "Active chart of accounts with codes, names and types",
        "mime_type": "application/json",
    },
    {
        "uri": "anerp://policies",
        "name": "policies",
        "description": "The active policy set (YAML) evaluated in simulate and commit",
        "mime_type": "application/yaml",
    },
    {
        "uri": "anerp://capabilities",
        "name": "capabilities",
        "description": "Tool catalog grouped by module with scopes (same as list_capabilities)",
        "mime_type": "application/json",
    },
    {
        "uri": "anerp://events/latest",
        "name": "events_latest",
        "description": "The last 50 events",
        "mime_type": "application/json",
    },
]


def list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            uri=r["uri"], name=r["name"], description=r["description"], mime_type=r["mime_type"]
        )
        for r in RESOURCES
    ]  # type: ignore[arg-type]


def read_resource(uri: str) -> tuple[str, str]:
    """Return (mime_type, text) for a resource uri."""
    if uri == "anerp://chart-of-accounts":
        with session_scope() as s:
            rows = s.exec(select(Account).order_by(Account.code)).all()  # type: ignore[arg-type]
            data: Any = [
                {"code": a.code, "name": a.name, "type": a.type, "is_active": a.is_active}
                for a in rows
            ]
        return "application/json", json.dumps(data, indent=2)
    if uri == "anerp://policies":
        return "application/yaml", get_engine().yaml_text
    if uri == "anerp://capabilities":
        return "application/json", json.dumps(registry.catalog(), indent=2)
    if uri == "anerp://events/latest":
        with session_scope() as s:
            rows = s.exec(select(Event).order_by(Event.seq.desc()).limit(50)).all()  # type: ignore[attr-defined]
            data = [event_to_dict(e) for e in reversed(rows)]
        return "application/json", json.dumps(data, indent=2, default=str)
    raise KeyError(uri)
