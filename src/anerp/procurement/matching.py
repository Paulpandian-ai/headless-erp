"""Three-way match computation (PO qty/price vs GRN qty vs invoice). Pure; policy decides."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from anerp.procurement.models import PurchaseOrderLine


@dataclass
class MatchLine:
    po_line: PurchaseOrderLine
    sku: str
    invoice_qty: int
    invoice_unit_cost_cents: int
    po_unit_cost_cents: int
    received_qty: int
    already_invoiced_qty: int

    @property
    def available_qty(self) -> int:
        return self.received_qty - self.already_invoiced_qty

    @property
    def qty_exceeded(self) -> bool:
        return self.invoice_qty > self.available_qty

    @property
    def unit_variance_cents(self) -> int:
        return self.invoice_unit_cost_cents - self.po_unit_cost_cents

    @property
    def variance_cents(self) -> int:
        return self.unit_variance_cents * self.invoice_qty

    @property
    def variance_abs_cents(self) -> int:
        return abs(self.unit_variance_cents)

    @property
    def variance_pct(self) -> float:
        if self.po_unit_cost_cents == 0:
            return 0.0 if self.unit_variance_cents == 0 else 100.0
        return round(abs(self.unit_variance_cents) / self.po_unit_cost_cents * 100, 4)

    @property
    def po_value_cents(self) -> int:
        return self.po_unit_cost_cents * self.invoice_qty

    @property
    def invoice_value_cents(self) -> int:
        return self.invoice_unit_cost_cents * self.invoice_qty

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "po_line_id": self.po_line.id,
            "invoice_qty": self.invoice_qty,
            "received_qty": self.received_qty,
            "already_invoiced_qty": self.already_invoiced_qty,
            "available_qty": self.available_qty,
            "qty_exceeded": self.qty_exceeded,
            "po_unit_cost_cents": self.po_unit_cost_cents,
            "invoice_unit_cost_cents": self.invoice_unit_cost_cents,
            "unit_variance_cents": self.unit_variance_cents,
            "variance_cents": self.variance_cents,
            "variance_abs_cents": self.variance_abs_cents,
            "variance_pct": self.variance_pct,
            "po_value_cents": self.po_value_cents,
            "invoice_value_cents": self.invoice_value_cents,
        }


@dataclass
class MatchResult:
    lines: list[MatchLine] = field(default_factory=list)

    @property
    def qty_exceeded(self) -> bool:
        return any(line.qty_exceeded for line in self.lines)

    @property
    def qty_exceeded_lines(self) -> list[str]:
        return [line.sku for line in self.lines if line.qty_exceeded]

    @property
    def variance_cents(self) -> int:
        return sum(line.variance_cents for line in self.lines)

    @property
    def max_variance_pct(self) -> float:
        return max((line.variance_pct for line in self.lines), default=0.0)

    @property
    def max_variance_abs_cents(self) -> int:
        return max((line.variance_abs_cents for line in self.lines), default=0)

    @property
    def po_value_cents(self) -> int:
        return sum(line.po_value_cents for line in self.lines)

    @property
    def invoice_value_cents(self) -> int:
        return sum(line.invoice_value_cents for line in self.lines)

    def facts(self) -> dict[str, Any]:
        return {
            "qty_exceeded": self.qty_exceeded,
            "qty_exceeded_lines": self.qty_exceeded_lines,
            "variance_cents": self.variance_cents,
            "max_variance_pct": self.max_variance_pct,
            "max_variance_abs_cents": self.max_variance_abs_cents,
            "po_value_cents": self.po_value_cents,
            "invoice_value_cents": self.invoice_value_cents,
            "lines": [line.as_dict() for line in self.lines],
        }
