from __future__ import annotations

from sqlalchemy import select

from ..audit.logger import audit, tool_call
from ..db import Customer, Order, Product, Review, Variant, session_scope
from ..models import SubmitReviewInput, SubmitReviewResponse, ToolError
from ..rating.bayesian import recompute_product_rating, sentiment_for_rating


async def submit_review(request: SubmitReviewInput, *, actor: str | None = None) -> SubmitReviewResponse | ToolError:
    actor = actor or f"customer:{request.customer_id}"
    async with session_scope() as session:
        tool_call(session, tool_name="submit_review", actor=actor, details=request.model_dump(mode="json"))
        customer = await session.get(Customer, request.customer_id)
        order = await session.get(Order, request.order_id)
        product = await session.get(Product, request.product_id)
        if customer is None or order is None or product is None or order.customer_id != request.customer_id or order.status != "paid":
            audit(session, actor=actor, event_type="review_rejected", entity_type="order", entity_id=request.order_id, details={"reason": "not_purchased"})
            await session.commit()
            return ToolError(error="not_purchased", message="Only the customer who completed a paid order can review this product.")

        variant = await session.get(Variant, order.variant_id)
        if variant is None or variant.product_id != request.product_id:
            audit(session, actor=actor, event_type="review_rejected", entity_type="order", entity_id=request.order_id, details={"reason": "product_mismatch"})
            await session.commit()
            return ToolError(error="not_purchased", message="That paid order was not for this product.")
        existing = await session.scalar(select(Review).where(Review.order_id == request.order_id))
        if existing is not None:
            audit(session, actor=actor, event_type="review_rejected", entity_type="order", entity_id=request.order_id, details={"reason": "already_reviewed"})
            await session.commit()
            return ToolError(error="already_reviewed", message="This order already has a review.")

        sentiment = sentiment_for_rating(request.rating)
        review = Review(product_id=request.product_id, customer_id=request.customer_id, order_id=request.order_id, rating=request.rating, text=request.text, sentiment=sentiment)
        session.add(review)
        await session.flush()
        await recompute_product_rating(session, product)
        audit(session, actor=actor, event_type="review_submitted", entity_type="review", entity_id=review.id, details={"product_id": request.product_id, "order_id": request.order_id, "rating": request.rating, "sentiment": sentiment})
        await session.commit()
        return SubmitReviewResponse(review_id=review.id, product_id=product.id, sentiment=sentiment, rating_avg=product.rating_avg, rating_count=product.rating_count, bayesian_rating=product.bayesian_rating)
