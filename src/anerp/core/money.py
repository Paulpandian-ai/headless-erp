"""Money helpers: payloads carry Decimal amounts (2dp); storage is integer minor units."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import Field

Money = Annotated[
    Decimal,
    Field(
        ge=0,
        decimal_places=2,
        max_digits=18,
        description="Amount in base currency, 2 decimals, e.g. 50.00",
    ),
]
PositiveMoney = Annotated[
    Decimal,
    Field(
        gt=0,
        decimal_places=2,
        max_digits=18,
        description="Amount in base currency, > 0, e.g. 50.00",
    ),
]
Qty = Annotated[int, Field(gt=0, description="Whole units, > 0")]


def cents(amount: Decimal | int | float | str) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents_value: int) -> str:
    sign = "-" if cents_value < 0 else ""
    value = abs(cents_value)
    return f"{sign}{value // 100}.{value % 100:02d}"
