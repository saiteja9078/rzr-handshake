"""Pydantic contracts for MCP tools and the webhook-facing API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CatalogSchemaResponse(BaseModel):
    categories: list[str]
    attributes_by_category: dict[str, list[str]]
    price_range: dict[str, Decimal | None]
    sort_options: list[str] = ["rating", "price_asc", "price_desc"]


class SearchFilters(BaseModel):
    category: str | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    min_rating: Decimal | None = Field(default=None, ge=0, le=5)
    attributes: dict[str, str] = Field(default_factory=dict)
    keyword: str | None = None
    sort_by: Literal["rating", "price_asc", "price_desc"] = "rating"
    page: int = Field(default=1, ge=1)

    @field_validator("max_price")
    @classmethod
    def max_not_below_min(cls, value: Decimal | None, info: Any) -> Decimal | None:
        minimum = info.data.get("min_price")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("max_price must be greater than or equal to min_price")
        return value


class RatingSummary(BaseModel):
    avg: Decimal
    count: int
    weighted: Decimal


class ReviewSummary(BaseModel):
    positive_count: int
    negative_count: int
    most_helpful_positive: dict[str, Any] | None = None
    most_helpful_negative: dict[str, Any] | None = None


class CatalogProduct(BaseModel):
    id: int
    name: str
    brand: str | None
    category: str
    price: Decimal
    mrp: Decimal | None
    discount_pct: Decimal
    rating: RatingSummary
    stock_status: Literal["in_stock", "low_stock", "out_of_stock"]
    review_summary: ReviewSummary


class SearchCatalogResponse(BaseModel):
    total_results: int
    page: int
    page_size: int
    products: list[CatalogProduct]


class ProductVariant(BaseModel):
    id: int
    attributes: dict[str, Any]
    price: Decimal
    mrp: Decimal | None
    stock_qty: int
    stock_status: Literal["in_stock", "low_stock", "out_of_stock"]


class ProductDetails(BaseModel):
    id: int
    name: str
    brand: str | None
    category: str
    description: str | None
    rating: RatingSummary


class ReviewOut(BaseModel):
    id: int
    rating: int
    text: str | None
    sentiment: str | None
    helpful_count: int
    created_at: str


class ProductDetailsResponse(BaseModel):
    product: ProductDetails
    variants: list[ProductVariant]
    reviews_page_1: list[ReviewOut]
    reviews_page: int = 1
    reviews_page_size: int


class MoreReviewsResponse(BaseModel):
    product_id: int
    page: int
    page_size: int
    total_reviews: int
    reviews: list[ReviewOut]


class CreateOrderInput(BaseModel):
    customer_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    variant_id: int = Field(ge=1)
    quantity: int = Field(ge=1)
    reasoning: str | None = None
    search_filters: dict[str, Any] | None = None


class CreateOrderResponse(BaseModel):
    order_id: int
    amount: Decimal
    payment_link: str
    status: Literal["awaiting_payment"]


class ToolError(BaseModel):
    error: str
    message: str
    limit: int | str | None = None
    requested: int | str | None = None


class OrderStatusInput(BaseModel):
    order_id: int = Field(ge=1)


class OrderStatusResponse(BaseModel):
    order_id: int
    status: str
    amount: Decimal
    product_name: str
    quantity: int
    paid_at: str | None = None
    message: str | None = None


class SubmitReviewInput(BaseModel):
    customer_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    order_id: int = Field(ge=1)
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(default=None, max_length=5000)


class SubmitReviewResponse(BaseModel):
    review_id: int
    product_id: int
    sentiment: Literal["positive", "neutral", "negative"]
    rating_avg: Decimal
    rating_count: int
    bayesian_rating: Decimal


class WebhookResponse(BaseModel):
    ok: bool
    order_id: int | None = None
    status: str | None = None
    message: str | None = None


class APIError(BaseModel):
    error: str
    message: str
