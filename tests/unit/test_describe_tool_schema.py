"""describe_tool returns a self-contained input schema: no $ref/$defs left for the reader."""

from __future__ import annotations

import json

from anerp.core.registry import registry
from anerp.finance.query_tools import inline_schema_refs


def test_inline_schema_refs_dereferences_defs() -> None:
    import anerp.procurement.tools  # noqa: F401  (registers receive_goods)

    schema = registry.get("receive_goods").input_schema()
    assert "$defs" in schema  # pydantic emits ReceiptLineInput as a definition
    out = json.dumps(inline_schema_refs(schema))
    assert "$ref" not in out and "$defs" not in out
    assert '"sku"' in out and '"qty"' in out  # the definition's fields are inlined


def test_inline_schema_refs_leaves_cycles_alone() -> None:
    cyclic = {
        "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}},
        "$ref": "#/$defs/Node",
    }
    out = inline_schema_refs(cyclic)
    assert out["type"] == "object" and out["properties"]["next"] == {"$ref": "#/$defs/Node"}
