from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select

from ..audit.logger import audit, tool_call
from ..config import settings
from ..db import Product, Variant, session_scope
from ..models import CatalogProduct, RatingSummary, ReviewSummary, SearchCatalogResponse, SearchFilters
from ..rating.bayesian import review_summary
from .common import decimal, discount_pct, stock_status


def _variant_matches(variant: Variant, filters: SearchFilters) -> bool:
    attrs = variant.attributes or {}
    for key, expected in filters.attributes.items():
        actual = attrs.get(key)
        if isinstance(actual, list):
            if expected not in [str(item) for item in actual]:
                return False
        elif str(actual).lower() != str(expected).lower():
            return False
    return True


async def search_catalog(filters: SearchFilters, *, actor: str = "agent") -> SearchCatalogResponse:
    async with session_scope() as session:
        tool_call(session, tool_name="search_catalog", actor=actor, details={"filters": filters.model_dump(mode="json")})
        products = (await session.scalars(select(Product))).all()
        all_variants = (await session.scalars(select(Variant))).all()
        variants_by_product: dict[int, list[Variant]] = {}
        for variant in all_variants:
            variants_by_product.setdefault(variant.product_id, []).append(variant)

        candidates: list[tuple[Product, list[Variant]]] = []
        keyword = filters.keyword.lower().strip() if filters.keyword else None
        for product in products:
            if filters.category and product.category.lower() != filters.category.lower():
                continue
            if keyword and keyword not in " ".join(filter(None, [product.name, product.brand, product.description])).lower():
                continue
            matching = [v for v in variants_by_product.get(product.id, []) if _variant_matches(v, filters)]
            if filters.min_price is not None:
                matching = [v for v in matching if decimal(v.price) >= filters.min_price]
            if filters.max_price is not None:
                matching = [v for v in matching if decimal(v.price) <= filters.max_price]
            if not matching:
                continue
            if decimal(product.bayesian_rating) < (filters.min_rating or Decimal("0")):
                continue
            candidates.append((product, matching))

        def key(item: tuple[Product, list[Variant]]) -> Any:
            product, variants = item
            price = min(decimal(v.price) for v in variants)
            if filters.sort_by == "price_asc":
                return price
            if filters.sort_by == "price_desc":
                return -price
            return -decimal(product.bayesian_rating)

        candidates.sort(key=key)
        total_results = len(candidates)
        page_size = min(filters.limit or settings.catalog_page_size, settings.catalog_max_page_size)
        start = (filters.page - 1) * page_size
        page_items = candidates[start : start + page_size]
        has_more = start + page_size < total_results
        output: list[CatalogProduct] = []
        for product, variants in page_items:
            price_variant = min(variants, key=lambda item: decimal(item.price))
            total_stock = sum(item.stock_qty for item in variants)
            output.append(
                CatalogProduct(
                    id=product.id,
                    name=product.name,
                    brand=product.brand,
                    category=product.category,
                    price=decimal(price_variant.price),
                    mrp=decimal(price_variant.mrp) if price_variant.mrp is not None else None,
                    discount_pct=discount_pct(decimal(price_variant.price), decimal(price_variant.mrp) if price_variant.mrp is not None else None),
                    rating=RatingSummary(avg=decimal(product.rating_avg), count=product.rating_count, weighted=decimal(product.bayesian_rating)),
                    stock_status=stock_status(total_stock),
                    review_summary=ReviewSummary(**(await review_summary(session, product.id))),
                )
            )
        audit(session, actor=actor, event_type="catalog_search", entity_type="catalog", details={"filters": filters.model_dump(mode="json"), "total_results": total_results})
        await session.commit()
        return SearchCatalogResponse(
            total_results=total_results,
            page=filters.page,
            page_size=page_size,
            has_more=has_more,
            next_page=filters.page + 1 if has_more else None,
            products=output,
        )
