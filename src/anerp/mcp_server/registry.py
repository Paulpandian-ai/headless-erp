"""Convert anerp tools into MCP tool definitions and route tools/call into the dispatcher."""

from __future__ import annotations

import json
from typing import Any

import mcp_types as types

from anerp.core.dispatch import dispatch, run_query
from anerp.core.envelope import Actor, Envelope, Principal
from anerp.core.errors import RETRY_ADVICE, ErrorCode
from anerp.core.registry import BaseTool, QueryTool, WriteTool, registry
from anerp.core.requestlog import log_auth_failure

ENVELOPE_FIELDS = ("mode", "idempotency_key", "simulation_id", "on_behalf_of")

ENVELOPE_PROPERTIES: dict[str, Any] = {
    "mode": {
        "type": "string",
        "enum": ["simulate", "commit"],
        "default": "simulate",
        "description": "simulate = validate + project effects + policy decision, nothing persisted. commit = persist (requires idempotency_key).",
    },
    "idempotency_key": {
        "type": "string",
        "minLength": 8,
        "maxLength": 128,
        "description": "Required on commit. Unique per intended operation; replaying the same key returns the original receipt.",
    },
    "simulation_id": {
        "type": "string",
        "description": "Optional on commit: the simulation_id from a prior simulate. The kernel refuses (STALE_SIMULATION) if touched documents changed since.",
    },
    "on_behalf_of": {
        "type": "string",
        "description": "Optional human id the agent acts for; recorded on the receipt for attribution only.",
    },
}


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten Pydantic $defs into the properties so the tool schema is self-contained."""
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                target = defs[node["$ref"].split("/")[-1]]
                merged = {**resolve(target), **{k: v for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def input_schema_for(tool: BaseTool) -> dict[str, Any]:
    payload = _inline_defs(tool.payload_model.model_json_schema())
    props = dict(payload.get("properties", {}))
    required = list(payload.get("required", []))
    if isinstance(tool, WriteTool):
        clash = set(props) & set(ENVELOPE_FIELDS)
        if clash:  # pragma: no cover - guarded by design
            raise ValueError(f"tool {tool.name} payload clashes with envelope fields {clash}")
        props = {**ENVELOPE_PROPERTIES, **props}
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def annotations_for(tool: BaseTool) -> types.ToolAnnotations:
    a = tool.annotations
    return types.ToolAnnotations(
        title=tool.name.replace("_", " "),
        read_only_hint=a.read_only,
        destructive_hint=False if a.read_only else a.destructive,
        idempotent_hint=a.idempotent,
        open_world_hint=False,
    )


def mcp_tools() -> list[types.Tool]:
    out = []
    for tool in registry.all():
        out.append(
            types.Tool(
                name=tool.name,
                description=tool.description(),
                input_schema=input_schema_for(tool),
                annotations=annotations_for(tool),
                meta={"module": tool.module, "scope": tool.scope, "kind": tool.kind},
            )
        )
    return out


def call_tool(
    name: str, arguments: dict[str, Any] | None, principal: Principal | None
) -> dict[str, Any]:
    """Split MCP arguments into envelope + payload and run through the single dispatcher."""
    args = dict(arguments or {})
    tool = registry.get(name)
    if tool is None:
        return {
            "ok": False,
            "error": {
                "code": "NOT_FOUND",
                "message": f"unknown tool {name}",
                "retry_advice": "Call list_capabilities.",
            },
        }
    if principal is None:
        mode = "query" if isinstance(tool, QueryTool) else str(args.get("mode", "simulate"))
        message = "no principal for this request"
        return {
            "ok": False,
            "mode": mode,
            "request_id": log_auth_failure(tool=name, mode=mode, message=message),
            "error": {
                "code": ErrorCode.UNAUTHORIZED.value,
                "message": message,
                "details": {},
                "retry_advice": RETRY_ADVICE[ErrorCode.UNAUTHORIZED],
            },
        }
    actor = principal.to_actor(on_behalf_of=args.pop("on_behalf_of", None))
    if isinstance(tool, QueryTool):
        for f in ENVELOPE_FIELDS:
            args.pop(f, None)
        return run_query(name, args, actor, principal=principal)
    mode = args.pop("mode", "simulate")
    key = args.pop("idempotency_key", None)
    sim = args.pop("simulation_id", None)
    try:
        env = Envelope(
            tool=name, mode=mode, idempotency_key=key, simulation_id=sim, actor=actor, payload=args
        )
    except Exception as exc:  # noqa: BLE001 - pydantic validation of the envelope itself
        return {
            "ok": False,
            "mode": mode,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": str(exc),
                "retry_advice": "Fix the envelope fields (mode, idempotency_key).",
            },
        }
    return dispatch(env, principal=principal)


def to_result(result: dict[str, Any]) -> types.CallToolResult:
    text = json.dumps(result, indent=2, default=str)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=result,
        is_error=not result.get("ok", False),
    )


__all__ = ["Actor", "call_tool", "input_schema_for", "mcp_tools", "to_result"]
