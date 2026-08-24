"""The single source of truth for money-action bounds."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config import settings

MAX_QTY = settings.max_qty
MAX_SPEND = settings.max_spend


@dataclass(frozen=True)
class BoundViolation:
    error: str
    limit: int | str
    requested: int | str
    message: str


def check_order_bounds(quantity: int, total: Decimal) -> BoundViolation | None:
    if quantity > MAX_QTY:
        return BoundViolation(
            error="exceeds_bounds",
            limit=MAX_QTY,
            requested=quantity,
            message=f"Quantity {quantity} exceeds the server limit of {MAX_QTY}.",
        )
    if total > MAX_SPEND:
        return BoundViolation(
            error="exceeds_bounds",
            limit=str(MAX_SPEND),
            requested=str(total),
            message=f"Total {total} exceeds the server spend limit of {MAX_SPEND}.",
        )
    return None
