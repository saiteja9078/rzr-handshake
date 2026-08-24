from __future__ import annotations

from sqlalchemy import func, select

from ..audit.logger import tool_call
from ..db import Product, Variant, session_scope
from ..models import CatalogSchemaResponse


async def get_catalog_schema(*, actor: str = "agent") -> CatalogSchemaResponse:
    async with session_scope() as session:
        categories = list((await session.scalars(select(Product.category).distinct().order_by(Product.category))).all())
        variants = (await session.scalars(select(Variant))).all()
        attributes_by_category: dict[str, set[str]] = {category: set() for category in categories}
        product_categories = dict((await session.execute(select(Product.id, Product.category))).all())
        for variant in variants:
            category = product_categories.get(variant.product_id)
            if category:
                attributes_by_category.setdefault(category, set()).update((variant.attributes or {}).keys())
        min_price, max_price = (await session.execute(select(func.min(Variant.price), func.max(Variant.price)))).one()
        tool_call(session, tool_name="get_catalog_schema", actor=actor)
        await session.commit()
        return CatalogSchemaResponse(
            categories=categories,
            attributes_by_category={key: sorted(value) for key, value in sorted(attributes_by_category.items())},
            price_range={"min": min_price, "max": max_price},
        )
