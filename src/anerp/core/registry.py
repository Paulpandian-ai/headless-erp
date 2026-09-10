"""Tool base classes and the global registry. Every tool (write, query, admin) lives here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from anerp.core.context import ToolContext
from anerp.core.projection import Projection


@dataclass
class Annotations:
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = True
    open_world: bool = False


class EmptyPayload(BaseModel):
    pass


class BaseTool:
    name: ClassVar[str]
    module: ClassVar[str]
    scope: ClassVar[str]
    purpose: ClassVar[str]
    payload_model: ClassVar[type[BaseModel]] = EmptyPayload
    annotations: ClassVar[Annotations] = Annotations()
    kind: ClassVar[str] = "write"  # write | query | admin

    @classmethod
    def parameter_names(cls) -> list[str]:
        """Payload field names in schema order (envelope fields are not payload)."""
        return list(cls.payload_model.model_fields)

    @classmethod
    def required_parameter_names(cls) -> list[str]:
        return [n for n, f in cls.payload_model.model_fields.items() if f.is_required()]

    @classmethod
    def signature(cls) -> str:
        """`tool_name(required, optional?)` - the first line of every description."""
        params = ", ".join(
            name if info.is_required() else f"{name}?"
            for name, info in cls.payload_model.model_fields.items()
        )
        return f"{cls.name}({params})"

    @classmethod
    def description(cls) -> str:
        return f"{cls.signature()}: {cls.purpose}"

    @classmethod
    def input_schema(cls) -> dict[str, Any]:
        return cls.payload_model.model_json_schema()


class WriteTool(BaseTool):
    """A two-phase business operation. Subclasses implement `project`."""

    preconditions: ClassVar[list[str]] = []
    effects: ClassVar[str] = ""
    compensating_tool: ClassVar[str | None] = None
    compensating_when: ClassVar[str] = ""
    common_errors: ClassVar[list[str]] = []
    emits: ClassVar[list[str]] = []

    def project(self, ctx: ToolContext, payload: Any) -> Projection:  # pragma: no cover - abstract
        raise NotImplementedError

    @classmethod
    def description(cls) -> str:
        """DESIGN.md §7.6 template, rendered verbatim in structure."""
        pre = (
            "; ".join(cls.preconditions) if cls.preconditions else "none beyond payload validation"
        )
        comp = (
            f"{cls.compensating_tool} ({cls.compensating_when})"
            if cls.compensating_tool
            else "none (this operation is terminal or is itself a reversal)"
        )
        errors = (
            "; ".join(cls.common_errors) if cls.common_errors else "VALIDATION_ERROR, NOT_FOUND"
        )
        return (
            f"{cls.signature()}: {cls.purpose}\n"
            f"Preconditions: {pre}.\n"
            f"Effects on commit: {cls.effects}\n"
            'Simulate first: call with mode="simulate" to see projected effects and policy decision '
            "without side effects.\n"
            "Idempotency: supply a unique idempotency_key on commit; replaying the same key returns "
            "the original receipt.\n"
            f"Compensating tool: {comp}.\n"
            f"Common errors: {errors}."
        )


class QueryTool(BaseTool):
    kind: ClassVar[str] = "query"
    annotations: ClassVar[Annotations] = Annotations(
        read_only=True, destructive=False, idempotent=True
    )

    def run(self, ctx: ToolContext, payload: Any) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


class AdminTool(WriteTool):
    """Admin actions are receipted write tools under `admin:*` scopes (DESIGN.md §7.8)."""

    kind: ClassVar[str] = "admin"


@dataclass
class Registry:
    tools: dict[str, BaseTool] = field(default_factory=dict)
    _loaded: bool = False

    def register(self, tool: BaseTool) -> BaseTool:
        self.tools[tool.name] = tool
        return tool

    def get(self, name: str) -> BaseTool | None:
        self.ensure_loaded()
        return self.tools.get(name)

    def all(self) -> list[BaseTool]:
        self.ensure_loaded()
        return list(self.tools.values())

    def write_tools(self) -> list[WriteTool]:
        return [t for t in self.all() if isinstance(t, WriteTool)]

    def query_tools(self) -> list[QueryTool]:
        return [t for t in self.all() if isinstance(t, QueryTool)]

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        # Import side effects register the tools; kept here to avoid circular imports.
        import anerp.admin.tools  # noqa: F401
        import anerp.approvals.tools  # noqa: F401
        import anerp.finance.query_tools  # noqa: F401
        import anerp.finance.tools  # noqa: F401
        import anerp.masterdata.tools  # noqa: F401
        import anerp.procurement.tools  # noqa: F401
        import anerp.sales.tools  # noqa: F401
        import anerp.troubleshoot.tools  # noqa: F401

    def catalog(self) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for tool in self.all():
            groups.setdefault(tool.module, []).append(
                {
                    "name": tool.name,
                    "signature": tool.signature(),
                    "kind": tool.kind,
                    "scope": tool.scope,
                    "summary": tool.purpose,
                    "compensating_tool": getattr(tool, "compensating_tool", None),
                    "read_only": tool.annotations.read_only,
                }
            )
        return {"modules": groups, "count": len(self.tools)}


registry = Registry()


def tool(cls_or_factory: Callable[[], BaseTool] | type[BaseTool]) -> Any:
    """Class decorator: instantiate and register."""
    instance = cls_or_factory()
    registry.register(instance)
    return cls_or_factory
