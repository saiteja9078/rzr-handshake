"""MCP server registration: only structured merchant tools are exposed here."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .models import CreateOrderInput, SearchFilters, SubmitReviewInput
from .tools.create_order import create_order as service_create_order
from .tools.get_catalog_schema import get_catalog_schema as service_get_catalog_schema
from .tools.get_more_reviews import get_more_reviews as service_get_more_reviews
from .tools.get_order_status import get_order_status as service_get_order_status
from .tools.get_product_details import get_product_details as service_get_product_details
from .tools.search_catalog import search_catalog as service_search_catalog
from .tools.submit_review import submit_review as service_submit_review

# The MCP app is mounted by FastAPI at /mcp, so its internal route must be /
# rather than the SDK's standalone-server default of /mcp.
mcp = FastMCP("Agent Commerce Protocol", streamable_http_path="/")


@mcp.tool()
async def get_catalog_schema() -> dict:
    """Return the typed catalog vocabulary. Cache this once per client session."""
    return (await service_get_catalog_schema()).model_dump(mode="json")


@mcp.tool()
async def search_catalog(filters: SearchFilters) -> dict:
    """Search products with typed filters; natural language is not accepted."""
    return (await service_search_catalog(filters)).model_dump(mode="json")


@mcp.tool()
async def get_product_details(product_id: int, variant_id: int | None = None) -> dict:
    """Return a product, its variants, stock, and the first review page."""
    result = await service_get_product_details(product_id, variant_id)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@mcp.tool()
async def get_more_reviews(product_id: int, page: int = 2) -> dict:
    """Fetch a later review page only when more evidence is needed."""
    result = await service_get_more_reviews(product_id, page)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@mcp.tool()
async def create_order(request: CreateOrderInput) -> dict:
    """Create an awaiting-payment order; this never marks an order paid."""
    result = await service_create_order(request)
    return result.model_dump(mode="json")


@mcp.tool()
async def get_order_status(order_id: int) -> dict:
    """Read verified order state; paid is only set by the webhook."""
    result = await service_get_order_status(order_id)
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


@mcp.tool()
async def submit_review(request: SubmitReviewInput) -> dict:
    """Submit one review after checking ownership and paid status."""
    result = await service_submit_review(request)
    return result.model_dump(mode="json")


def asgi_app():
    """Use the streamable-HTTP transport supplied by the official MCP SDK."""
    if hasattr(mcp, "streamable_http_app"):
        return mcp.streamable_http_app()
    # Compatibility with older SDK releases that named this helper http_app.
    if hasattr(mcp, "http_app"):
        return mcp.http_app(transport="streamable-http")
    raise RuntimeError("Installed MCP SDK does not expose streamable HTTP transport")
