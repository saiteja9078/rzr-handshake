"""Deterministic product ratings and review summaries."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Product, Review

MIN_VOTES = 25
DEFAULT_GLOBAL_PRIOR = Decimal("3.00")


def sentiment_for_rating(rating: int) -> str:
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def weighted_rating(rating_avg: Decimal, rating_count: int, global_prior: Decimal = DEFAULT_GLOBAL_PRIOR, minimum_votes: int = MIN_VOTES) -> Decimal:
    if rating_count <= 0:
        return global_prior.quantize(Decimal("0.01"))
    value = (Decimal(rating_count) / (Decimal(rating_count) + minimum_votes)) * rating_avg
    value += (Decimal(minimum_votes) / (Decimal(rating_count) + minimum_votes)) * global_prior
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def global_rating_prior(session: AsyncSession) -> Decimal:
    total = await session.scalar(select(func.coalesce(func.sum(Review.rating), 0)))
    count = await session.scalar(select(func.count(Review.id)))
    if not count:
        return DEFAULT_GLOBAL_PRIOR
    return (Decimal(str(total)) / Decimal(count)).quantize(Decimal("0.01"))


async def recompute_product_rating(session: AsyncSession, product: Product) -> None:
    total = await session.scalar(select(func.coalesce(func.sum(Review.rating), 0)).where(Review.product_id == product.id))
    count = await session.scalar(select(func.count(Review.id)).where(Review.product_id == product.id))
    count = int(count or 0)
    total_decimal = Decimal(str(total or 0))
    average = (total_decimal / count).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if count else Decimal("0.0")
    prior = await global_rating_prior(session)
    product.rating_avg = average
    product.rating_count = count
    product.bayesian_rating = weighted_rating(average, count, prior)


async def review_summary(session: AsyncSession, product_id: int) -> dict[str, Any]:
    rows = (await session.scalars(select(Review).where(Review.product_id == product_id))).all()
    positive = [r for r in rows if r.sentiment == "positive"]
    negative = [r for r in rows if r.sentiment == "negative"]

    def best(items: list[Review]) -> dict[str, Any] | None:
        if not items:
            return None
        row = max(items, key=lambda item: (item.helpful_count or 0, item.created_at))
        return {"rating": row.rating, "text": row.text, "helpful_count": row.helpful_count or 0}

    return {
        "positive_count": len(positive),
        "negative_count": len(negative),
        "most_helpful_positive": best(positive),
        "most_helpful_negative": best(negative),
    }
