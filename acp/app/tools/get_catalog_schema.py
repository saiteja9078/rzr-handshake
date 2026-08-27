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
        attribute_values_by_category: dict[str, dict[str, set[str]]] = {category: {} for category in categories}
        product_categories = dict((await session.execute(select(Product.id, Product.category))).all())
        for variant in variants:
            category = product_categories.get(variant.product_id)
            if category:
                attributes = variant.attributes or {}
                attributes_by_category.setdefault(category, set()).update(attributes.keys())
                values_for_category = attribute_values_by_category.setdefault(category, {})
                for name, value in attributes.items():
                    values_for_category.setdefault(name, set()).add(str(value))
        min_price, max_price = (await session.execute(select(func.min(Variant.price), func.max(Variant.price)))).one()
        tool_call(session, tool_name="get_catalog_schema", actor=actor)
        await session.commit()
        return CatalogSchemaResponse(
            categories=categories,
            attributes_by_category={key: sorted(value) for key, value in sorted(attributes_by_category.items())},
            attribute_values_by_category={
                category: {name: sorted(values) for name, values in sorted(attributes.items())}
                for category, attributes in sorted(attribute_values_by_category.items())
            },
            price_range={"min": min_price, "max": max_price},
        )
