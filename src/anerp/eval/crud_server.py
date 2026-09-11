"""# BASELINE ONLY - the control server for the ablation (DESIGN.md §14.1).

Generic row tools over the same tables with field-name-only descriptions and no simulate,
idempotency, policy or receipts. It deliberately bypasses `core.dispatch`; nothing else may.
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlmodel import SQLModel

from anerp.core.ids import new_ulid, utcnow
from anerp.db import session_scope

BUSINESS_TABLES = [
    "account",
    "supplier",
    "customer",
    "item",
    "fiscal_period",
    "journal_entry",
    "journal_line",
    "open_item",
    "purchase_order",
    "purchase_order_line",
    "goods_receipt",
    "supplier_invoice",
    "supplier_payment",
    "sales_order",
    "sales_order_line",
    "shipment",
    "customer_invoice",
    "customer_payment",
    "credit_note",
]


def _columns(table: str) -> list[str]:
    import anerp.models  # noqa: F401

    return [c.name for c in SQLModel.metadata.tables[table].columns]


def crud_tools() -> list[dict[str, Any]]:
    tables = {t: _columns(t) for t in BUSINESS_TABLES}
    return [
        {
            "name": "list_tables",
            "description": "List table names and their columns.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_rows",
            "description": "Rows from a table. Tables: " + ", ".join(tables),
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "filters": {"type": "object", "description": "column: value equality filters"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["table"],
            },
        },
        {
            "name": "get_row",
            "description": "One row by id.",
            "input_schema": {
                "type": "object",
                "properties": {"table": {"type": "string"}, "id": {"type": "string"}},
                "required": ["table", "id"],
            },
        },
        {
            "name": "insert_row",
            "description": "Insert a row. Columns per table: " + json.dumps(tables),
            "input_schema": {
                "type": "object",
                "properties": {"table": {"type": "string"}, "values": {"type": "object"}},
                "required": ["table", "values"],
            },
        },
        {
            "name": "update_row",
            "description": "Update columns of a row by id.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "id": {"type": "string"},
                    "values": {"type": "object"},
                },
                "required": ["table", "id", "values"],
            },
        },
    ]


def _coerce(table: str, values: dict[str, Any]) -> dict[str, Any]:
    cols = SQLModel.metadata.tables[table].columns
    out: dict[str, Any] = {}
    for k, v in values.items():
        if k not in cols:
            raise ValueError(f"unknown column {k} for {table}")
        col = cols[k]
        if isinstance(v, dict | list) and col.type.__class__.__name__ == "JSON":
            out[k] = json.dumps(v)
        else:
            out[k] = v
    return out


CALL_LOG: list[dict[str, Any]] = []
"""Every crud_call in this process (name, arguments, ok, latency_ms); the runner drains it after
each run so SDK clients reaching the baseline over HTTP still get a tool-call trace."""


def drain_call_log() -> list[dict[str, Any]]:
    calls = list(CALL_LOG)
    CALL_LOG.clear()
    return calls


def crud_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        out: dict[str, Any] = {"ok": True, "result": _crud(name, args)}
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": {"code": "ERROR", "message": f"{type(exc).__name__}: {exc}"}}
    CALL_LOG.append(
        {
            "name": name,
            "arguments": args,
            "ok": out["ok"],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    )
    return out


def _crud(name: str, args: dict[str, Any]) -> Any:
    if name == "list_tables":
        return {t: _columns(t) for t in BUSINESS_TABLES}
    table = args.get("table", "")
    if table not in BUSINESS_TABLES:
        raise ValueError(f"unknown table {table}")
    with session_scope() as s:
        if name == "list_rows":
            filters = args.get("filters") or {}
            where = " AND ".join(f"{k} = :{k}" for k in filters) or "1=1"
            for k in filters:
                if k not in _columns(table):
                    raise ValueError(f"unknown column {k}")
            rows = (
                s.execute(
                    text(f"SELECT * FROM {table} WHERE {where} LIMIT :limit"),
                    {**filters, "limit": int(args.get("limit", 50))},
                )
                .mappings()
                .all()
            )
            return [dict(r) for r in rows]
        if name == "get_row":
            row = (
                s.execute(text(f"SELECT * FROM {table} WHERE id = :id"), {"id": args["id"]})
                .mappings()
                .first()
            )
            return dict(row) if row else None
        if name == "insert_row":
            values = _coerce(table, dict(args.get("values") or {}))
            cols = _columns(table)
            if "id" in cols and "id" not in values:
                values["id"] = new_ulid()
            now = utcnow().isoformat()
            for c in ("created_at", "updated_at"):
                if c in cols and c not in values:
                    values[c] = now
            if "state_version" in cols and "state_version" not in values:
                values["state_version"] = 1
            for col in SQLModel.metadata.tables[
                table
            ].columns:  # scalar ORM defaults act as DB defaults
                if (
                    col.name not in values
                    and col.default is not None
                    and getattr(col.default, "is_scalar", False)
                ):
                    values[col.name] = col.default.arg
            s.execute(
                text(
                    f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
                ),
                values,
            )
            return {"inserted": True, "id": values.get("id")}
        if name == "update_row":
            values = _coerce(table, dict(args.get("values") or {}))
            if not values:
                raise ValueError("no values")
            sets = ", ".join(f"{k} = :{k}" for k in values)
            res = s.execute(
                text(f"UPDATE {table} SET {sets} WHERE id = :_id"), {**values, "_id": args["id"]}
            )
            return {"updated": res.rowcount}
    raise ValueError(f"unknown tool {name}")


def build_crud_mcp_server() -> Any:
    """Expose the baseline over MCP (streamable HTTP or stdio) for remote SDK clients."""
    import anyio
    import mcp_types as types
    from mcp.server.lowlevel import Server

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=t["name"], description=t["description"], input_schema=t["input_schema"]
                )
                for t in crud_tools()
            ]
        )

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = await anyio.to_thread.run_sync(crud_call, params.name, params.arguments or {})
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, default=str))],
            structured_content=result,
            is_error=not result.get("ok"),
        )

    return Server(
        "anerp-crud-baseline",
        instructions="Generic table access to an ERP database. BASELINE ONLY.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


__all__ = ["build_crud_mcp_server", "crud_call", "crud_tools", "drain_call_log", "sa_inspect"]
