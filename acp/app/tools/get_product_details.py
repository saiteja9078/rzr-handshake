from __future__ import annotations

from sqlalchemy import select

from ..audit.logger import audit, tool_call
from ..config import settings
from ..db import Product, Review, Variant, session_scope
from ..models import ProductDetails, ProductDetailsResponse, ProductVariant, RatingSummary
from ..rating.bayesian import review_summary
from .common import decimal, review_dict, stock_status


async def get_product_details(product_id: int, variant_id: int | None = None, *, actor: str = "agent") -> ProductDetailsResponse | dict:
    async with session_scope() as session:
        tool_call(session, tool_name="get_product_details", actor=actor, details={"product_id": product_id, "variant_id": variant_id})
        product = await session.get(Product, product_id)
        if product is None:
            audit(session, actor=actor, event_type="catalog_not_found", entity_type="product", entity_id=product_id)
            await session.commit()
            return {"error": "not_found", "message": "Product not found."}
        query = select(Variant).where(Variant.product_id == product_id)
        if variant_id is not None:
            query = query.where(Variant.id == variant_id)
        variants = (await session.scalars(query.order_by(Variant.id))).all()
        if variant_id is not None and not variants:
            audit(session, actor=actor, event_type="variant_not_found", entity_type="variant", entity_id=variant_id)
            await session.commit()
            return {"error": "not_found", "message": "Variant does not belong to this product."}
        reviews = (await session.scalars(select(Review).where(Review.product_id == product_id).order_by(Review.helpful_count.desc(), Review.created_at.desc()).limit(settings.reviews_page_size))).all()
        await session.commit()
        return ProductDetailsResponse(
            product=ProductDetails(
                id=product.id,
                name=product.name,
                brand=product.brand,
                category=product.category,
                description=product.description,
                rating=RatingSummary(avg=decimal(product.rating_avg), count=product.rating_count, weighted=decimal(product.bayesian_rating)),
            ),
            variants=[ProductVariant(id=v.id, attributes=v.attributes or {}, price=decimal(v.price), mrp=decimal(v.mrp) if v.mrp is not None else None, stock_qty=v.stock_qty, stock_status=stock_status(v.stock_qty)) for v in variants],
            reviews_page_1=[review_dict(row) for row in reviews],
            reviews_page_size=settings.reviews_page_size,
        )
