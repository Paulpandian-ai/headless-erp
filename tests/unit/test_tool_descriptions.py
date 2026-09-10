"""Every tool's description opens with its parameter names (the facade and MCP both rely on it)."""

from __future__ import annotations

import re

from anerp.core.registry import WriteTool, registry

SIGNATURE = re.compile(r"^(?P<name>\w+)\((?P<params>[^)]*)\): ")


def test_every_description_starts_with_the_parameter_signature() -> None:
    tools = registry.all()
    assert tools
    for tool in tools:
        first = tool.description().splitlines()[0]
        match = SIGNATURE.match(first)
        assert match, f"{tool.name} first line is not a signature: {first!r}"
        assert match.group("name") == tool.name
        listed = [p.strip().rstrip("?") for p in match.group("params").split(",") if p.strip()]
        assert listed == tool.parameter_names(), tool.name
        # `?` marks optional, so the unmarked names are exactly the required ones.
        unmarked = [
            p.strip() for p in match.group("params").split(",") if p.strip() and "?" not in p
        ]
        assert unmarked == tool.required_parameter_names(), tool.name


def test_write_descriptions_keep_the_design_template_below_the_signature() -> None:
    for tool in registry.write_tools():
        lines = tool.description().splitlines()
        assert lines[1].startswith("Preconditions:")
        assert lines[2].startswith("Effects on commit:")
        assert any(line.startswith("Compensating tool:") for line in lines)
        assert any(line.startswith("Common errors:") for line in lines)


def test_tools_with_no_payload_render_empty_parentheses() -> None:
    empty = [t for t in registry.all() if not t.parameter_names()]
    assert empty
    for tool in empty:
        assert tool.description().startswith(f"{tool.name}(): ")


def test_catalog_exposes_the_signature() -> None:
    catalog = registry.catalog()
    entries = [e for group in catalog["modules"].values() for e in group]
    assert entries
    for entry in entries:
        tool = registry.get(entry["name"])
        assert tool is not None
        assert entry["signature"] == tool.signature()
        if isinstance(tool, WriteTool):
            assert entry["signature"].startswith(f"{entry['name']}(")
