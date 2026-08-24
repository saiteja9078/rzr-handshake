"""Shared serialization and catalog helpers."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def discount_pct(price: Decimal, mrp: Decimal | None) -> Decimal:
    if not mrp or mrp <= 0 or mrp <= price:
        return Decimal("0.00")
    return ((mrp - price) / mrp * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def stock_status(stock_qty: int) -> str:
    if stock_qty <= 0:
        return "out_of_stock"
    if stock_qty <= 3:
        return "low_stock"
    return "in_stock"


def review_dict(review: Any) -> dict[str, Any]:
    created_at = review.created_at.isoformat() if review.created_at else ""
    return {
        "id": review.id,
        "rating": review.rating,
        "text": review.text,
        "sentiment": review.sentiment,
        "helpful_count": review.helpful_count or 0,
        "created_at": created_at,
    }
