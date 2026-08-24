from __future__ import annotations

from sqlalchemy import func, select

from ..audit.logger import audit, tool_call
from ..config import settings
from ..db import Product, Review, session_scope
from ..models import MoreReviewsResponse
from .common import review_dict


async def get_more_reviews(product_id: int, page: int = 2, *, actor: str = "agent") -> MoreReviewsResponse | dict:
    async with session_scope() as session:
        tool_call(session, tool_name="get_more_reviews", actor=actor, details={"product_id": product_id, "page": page})
        product = await session.get(Product, product_id)
        if product is None:
            audit(session, actor=actor, event_type="catalog_not_found", entity_type="product", entity_id=product_id)
            await session.commit()
            return {"error": "not_found", "message": "Product not found."}
        page = max(page, 1)
        offset = (page - 1) * settings.reviews_page_size
        rows = (await session.scalars(select(Review).where(Review.product_id == product_id).order_by(Review.helpful_count.desc(), Review.created_at.desc()).offset(offset).limit(settings.reviews_page_size))).all()
        total = int(await session.scalar(select(func.count(Review.id)).where(Review.product_id == product_id)) or 0)
        await session.commit()
        return MoreReviewsResponse(product_id=product_id, page=page, page_size=settings.reviews_page_size, total_reviews=total, reviews=[review_dict(row) for row in rows])
