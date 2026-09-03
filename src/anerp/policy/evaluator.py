"""A tiny safe expression evaluator over a facts dict (no `eval`, whitelisted AST nodes only)."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMP_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "max": max,
    "min": min,
    "len": len,
    "any": any,
    "all": all,
    "sum": sum,
    "round": round,
    "int": int,
    "str": str,
    "bool": bool,
}


class UnsafeExpression(ValueError):
    pass


class _Missing:
    """Sentinel for unknown names/attributes: comparisons with it are False, truthiness False."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "<missing>"


MISSING = _Missing()


def compile_expression(source: str) -> ast.Expression:
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError as exc:  # pragma: no cover - reported at load time
        raise UnsafeExpression(f"invalid expression: {source!r}: {exc}") from exc
    for node in ast.walk(tree):
        if (
            isinstance(
                node,
                ast.Expression
                | ast.BoolOp
                | ast.And
                | ast.Or
                | ast.UnaryOp
                | ast.Not
                | ast.USub
                | ast.BinOp
                | ast.Compare
                | ast.Name
                | ast.Load
                | ast.Attribute
                | ast.Subscript
                | ast.Constant
                | ast.Call
                | ast.List
                | ast.Tuple
                | ast.IfExp
                | ast.comprehension
                | ast.ListComp
                | ast.GeneratorExp
                | ast.Store,
            )
            or type(node) in _BIN_OPS
            or type(node) in _CMP_OPS
        ):
            continue
        raise UnsafeExpression(f"disallowed syntax {type(node).__name__} in {source!r}")
    return tree


def evaluate(tree: ast.Expression, facts: dict[str, Any]) -> Any:
    return _Evaluator(facts).visit(tree.body)


class _Evaluator:
    def __init__(self, facts: dict[str, Any]) -> None:
        self.scopes: list[dict[str, Any]] = [facts]

    def lookup(self, name: str) -> Any:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if name in ("None", "True", "False"):
            return {"None": None, "True": True, "False": False}[name]
        return MISSING

    def visit(self, node: ast.AST) -> Any:
        method = getattr(self, f"v_{type(node).__name__}", None)
        if method is None:
            raise UnsafeExpression(f"unsupported node {type(node).__name__}")
        return method(node)

    def v_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def v_Name(self, node: ast.Name) -> Any:
        return self.lookup(node.id)

    def v_Attribute(self, node: ast.Attribute) -> Any:
        if node.attr.startswith("_"):
            raise UnsafeExpression("private attribute access is not allowed")
        base = self.visit(node.value)
        if isinstance(base, dict):
            return base.get(node.attr, MISSING)
        if base is MISSING or base is None:
            return MISSING
        return getattr(base, node.attr, MISSING)

    def v_Subscript(self, node: ast.Subscript) -> Any:
        base = self.visit(node.value)
        key = self.visit(node.slice)
        try:
            return base[key]
        except (KeyError, IndexError, TypeError):
            return MISSING

    def v_List(self, node: ast.List) -> list[Any]:
        return [self.visit(e) for e in node.elts]

    def v_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:
        return tuple(self.visit(e) for e in node.elts)

    def v_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = self.visit(v)
                if not result:
                    return result
            return result
        for v in node.values:
            result = self.visit(v)
            if result:
                return result
        return False

    def v_UnaryOp(self, node: ast.UnaryOp) -> Any:
        val = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not val
        if isinstance(node.op, ast.USub):
            return -val if val is not MISSING else MISSING
        raise UnsafeExpression("unsupported unary operator")

    def v_BinOp(self, node: ast.BinOp) -> Any:
        left, right = self.visit(node.left), self.visit(node.right)
        if left is MISSING or right is MISSING:
            return MISSING
        try:
            return _BIN_OPS[type(node.op)](left, right)
        except (TypeError, ZeroDivisionError):
            return MISSING

    def v_Compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = self.visit(comparator)
            if left is MISSING or right is MISSING:
                return False
            try:
                if not _CMP_OPS[type(op)](left, right):
                    return False
            except TypeError:
                return False
            left = right
        return True

    def v_IfExp(self, node: ast.IfExp) -> Any:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def v_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise UnsafeExpression("only whitelisted functions may be called")
        args = [self.visit(a) for a in node.args]
        if any(a is MISSING for a in args):
            return MISSING
        try:
            return _FUNCS[node.func.id](*args)
        except (TypeError, ValueError):
            return MISSING

    def _comprehension(self, node: ast.ListComp | ast.GeneratorExp) -> list[Any]:
        out: list[Any] = []

        def rec(gens: list[ast.comprehension]) -> None:
            if not gens:
                out.append(self.visit(node.elt))
                return
            gen = gens[0]
            iterable = self.visit(gen.iter)
            if iterable is MISSING or iterable is None:
                return
            for item in iterable:
                self.scopes.append({})
                self._bind(gen.target, item)
                if all(self.visit(cond) for cond in gen.ifs):
                    rec(gens[1:])
                self.scopes.pop()

        rec(list(node.generators))
        return out

    def _bind(self, target: ast.AST, value: Any) -> None:
        if isinstance(target, ast.Name):
            self.scopes[-1][target.id] = value
        elif isinstance(target, ast.Tuple):
            for t, v in zip(target.elts, value, strict=False):
                self._bind(t, v)
        else:
            raise UnsafeExpression("unsupported comprehension target")

    def v_ListComp(self, node: ast.ListComp) -> list[Any]:
        return self._comprehension(node)

    def v_GeneratorExp(self, node: ast.GeneratorExp) -> list[Any]:
        return self._comprehension(node)
