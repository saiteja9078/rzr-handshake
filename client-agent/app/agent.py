"""A small, deterministic client agent proving the ACP flow end to end.

The parser is intentionally replaceable. It converts the user's text into the
same typed MCP arguments an LLM-backed parser would produce, while keeping the
demo runnable without a model key or provider dependency.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

try:  # works both as ``python client-agent/app/agent.py`` and as a package
    from .mcp_client import ACPClient
    from .session_store import SessionStore
except ImportError:  # pragma: no cover - direct CLI execution
    from mcp_client import ACPClient
    from session_store import SessionStore


@dataclass
class RuleBasedIntentParser:
    schema: dict[str, Any]

    def requested_count(self, text: str) -> int | None:
        """Extract a result count without treating price numbers as counts."""
        lowered = text.lower()
        patterns = [
            r"\b(?:show|find|give|list|display|recommend|suggest)\s+(?:me\s+)?(?:the\s+)?(?:top\s+)?(\d+)\b",
            r"\btop\s+(\d+)\b",
            r"\b(\d+)\s+(?:products?|items?|results?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return int(match.group(1))
        for category in self.schema.get("categories", []):
            match = re.search(rf"\b(\d+)\s+{re.escape(category.lower())}\b", lowered)
            if match:
                return int(match.group(1))
        return None

    def _keyword(self, text: str, category: str | None) -> str | None:
        if category:
            return None
        keyword = text.strip()
        keyword = re.sub(r"^(?:show|find|give|list|display|recommend|suggest)\s+(?:me\s+)?", "", keyword, flags=re.IGNORECASE)
        keyword = re.sub(r"\b(?:top\s+)?\d+\s+(?:products?|items?|results?)?\b", "", keyword, flags=re.IGNORECASE)
        keyword = re.sub(r"\b(?:under|below|less than|upto|up to|over|above|from|at least)\s*[₹$]?[\d,]+(?:\.\d+)?", "", keyword, flags=re.IGNORECASE)
        keyword = re.sub(r"\b[1-5](?:\.\d+)?\s*(?:star|stars|rating)\b", "", keyword, flags=re.IGNORECASE)
        keyword = re.sub(r"\b(?:cheapest|lowest price|price low|most expensive|highest price|price high)\b", "", keyword, flags=re.IGNORECASE)
        keyword = re.sub(r"\s+", " ", keyword).strip(" ,")
        return keyword or None

    def filters(self, text: str) -> dict[str, Any]:
        lowered = text.lower()
        categories = self.schema.get("categories", [])
        category = next((value for value in categories if re.search(rf"(?<!\w){re.escape(value.lower())}(?!\w)", lowered)), None)
        def number_after(patterns: list[str]) -> str | None:
            for pattern in patterns:
                match = re.search(pattern, lowered)
                if match:
                    return match.group(1).replace(",", "")
            return None
        minimum = number_after([r"(?:over|above|from|at least)\s*[₹$]?([\d,]+(?:\.\d+)?)"])
        maximum = number_after([r"(?:under|below|less than|upto|up to)\s*[₹$]?([\d,]+(?:\.\d+)?)"])
        rating_match = re.search(r"([1-5](?:\.\d+)?)\s*(?:star|stars|rating)", lowered)
        sort_by = "rating"
        if any(word in lowered for word in ("cheapest", "lowest price", "price low")):
            sort_by = "price_asc"
        elif any(word in lowered for word in ("most expensive", "highest price", "price high")):
            sort_by = "price_desc"
        attributes: dict[str, str] = {}
        attributes_by_category = self.schema.get("attributes_by_category", {})
        values_by_category = self.schema.get("attribute_values_by_category", {})
        categories = [category] if category else list(attributes_by_category)
        for current_category in categories:
            for attribute in attributes_by_category.get(current_category, []):
                explicit = re.search(rf"\b{re.escape(attribute)}\s*[:=]\s*([\w-]+)", lowered)
                if explicit:
                    attributes[attribute] = explicit.group(1)
                    continue
                values = values_by_category.get(current_category, {}).get(attribute, [])
                for value in sorted(values, key=len, reverse=True):
                    if re.search(rf"(?<!\w){re.escape(str(value).lower())}(?!\w)", lowered):
                        attributes[attribute] = str(value)
                        break
        requested_count = self.requested_count(text)
        return {
            "category": category,
            "min_price": minimum,
            "max_price": maximum,
            "min_rating": rating_match.group(1) if rating_match else None,
            "attributes": attributes,
            "keyword": self._keyword(text, category),
            "sort_by": sort_by,
            "page": 1,
            "limit": min(requested_count, 100) if requested_count else None,
            "requested_count": requested_count,
        }


class CommerceAgent:
    def __init__(self, client: ACPClient, store: SessionStore | None = None) -> None:
        self.client = client
        self.store = store or SessionStore(os.getenv("CLIENT_SESSION_DB", "./client-agent/session.sqlite3"))
        self._schema: dict[str, Any] | None = None
        self._parser: RuleBasedIntentParser | None = None

    async def start(self) -> dict[str, Any]:
        if self._schema is None:
            self._schema = await self.client.call("get_catalog_schema")
            self._parser = RuleBasedIntentParser(self._schema)
        return self._schema

    async def search(self, customer_id: int, text: str) -> str:
        await self.start()
        assert self._parser is not None
        raw_filters = self._parser.filters(text)
        requested_count = raw_filters.pop("requested_count", None)
        filters = {key: value for key, value in raw_filters.items() if value is not None and value != {}}
        result = await self.client.call("search_catalog", {"filters": filters})
        products = result.get("products", [])
        # A requested count can span several server pages. The server caps a
        # single page, while the client gathers only as many cards as asked for.
        while requested_count and len(products) < requested_count and result.get("has_more"):
            next_page = result.get("next_page") or (int(result.get("page", 1)) + 1)
            result = await self.client.call("search_catalog", {"filters": dict(filters, page=next_page)})
            products.extend(result.get("products", []))
        if requested_count:
            products = products[:requested_count]
        self.store.append_message(customer_id, "assistant", str({**result, "products": products}))
        if not products:
            return "I couldn't find a matching product."
        lines = [f"Found {result.get('total_results', len(products))} matching result(s); showing {len(products)} product card(s):"]
        for index, item in enumerate(products, start=1):
            rating = item.get("rating", {})
            review_summary = item.get("review_summary", {})
            lines.extend(
                [
                    "┌────────────────────────────────────────",
                    f"│ CARD {index}  ·  product #{item['id']}",
                    f"│ {item['name']}" + (f" · {item['brand']}" if item.get("brand") else ""),
                    f"│ {item['category']}  ·  ₹{item['price']}" + (f" (MRP ₹{item['mrp']})" if item.get("mrp") else ""),
                    f"│ rating {rating.get('weighted')} ({rating.get('count')} reviews)  ·  {item['stock_status']}",
                    f"│ reviews: {review_summary.get('positive_count', 0)} positive / {review_summary.get('negative_count', 0)} negative",
                    "└────────────────────────────────────────",
                ]
            )
        lines.append("Add one with: add product <id> variant <id> quantity <n>. Say 'cart' or 'confirm' when ready.")
        return "\n".join(lines)

    @staticmethod
    def _purchase_args(text: str) -> tuple[int | None, int | None, int]:
        product = re.search(r"product\s*#?\s*(\d+)", text.lower())
        variant = re.search(r"variant\s*#?\s*(\d+)", text.lower())
        quantity = re.search(r"(?:quantity|qty|buy|order)\s*(?:of\s*)?(\d+)\b", text.lower())
        return (int(product.group(1)) if product else None, int(variant.group(1)) if variant else None, int(quantity.group(1)) if quantity else 1)

    async def prepare_purchase(self, customer_id: int, text: str) -> str:
        product_id, variant_id, quantity = self._purchase_args(text)
        if product_id is None or variant_id is None:
            return "Please specify both product and variant IDs, for example: buy product 4 variant 7 quantity 2."
        details = await self.client.call("get_product_details", {"product_id": product_id, "variant_id": variant_id})
        if details.get("error"):
            return details.get("message", "I could not load that variant.")
        variant = next((item for item in details.get("variants", []) if item.get("id") == variant_id), None)
        if not variant:
            return "That variant is no longer available."
        self.store.clear_pending_action(customer_id)
        line_quantity = self.store.add_cart_item(customer_id, product_id=product_id, variant_id=variant_id, quantity=quantity)
        line_total = (Decimal(str(variant["price"])) * line_quantity).quantize(Decimal("0.01"))
        return f"Added {details['product']['name']} / variant {variant_id} to your cart. Line quantity: {line_quantity}, current line total: ₹{line_total}, stock currently shows {variant['stock_qty']}. Add more products or reply 'confirm' to checkout."

    async def show_cart(self, customer_id: int) -> str:
        items = self.store.cart_items(customer_id)
        if not items:
            return "Your cart is empty."
        lines = [f"Cart: {len(items)} product line(s)"]
        total = Decimal("0.00")
        for index, item in enumerate(items, start=1):
            details = await self.client.call("get_product_details", {"product_id": item["product_id"], "variant_id": item["variant_id"]})
            variant = next((candidate for candidate in details.get("variants", []) if candidate.get("id") == item["variant_id"]), None)
            if not variant:
                lines.append(f"{index}. product #{item['product_id']} / variant #{item['variant_id']} is no longer available")
                continue
            line_total = (Decimal(str(variant["price"])) * item["quantity"]).quantize(Decimal("0.01"))
            total += line_total
            product_name = details.get("product", {}).get("name", "Product")
            lines.append(f"{index}. {product_name} / variant #{item['variant_id']} × {item['quantity']} = ₹{line_total} · stock {variant['stock_qty']}")
        lines.append(f"Cart total: ₹{total}. Reply 'confirm' to create payment links for the cart items.")
        return "\n".join(lines)

    async def product_details(self, customer_id: int, text: str) -> str:
        match = re.search(r"product\s*#?\s*(\d+)", text.lower())
        if not match:
            return "Please specify a product ID, for example: details product 4."
        product_id = int(match.group(1))
        result = await self.client.call("get_product_details", {"product_id": product_id})
        if result.get("error"):
            return result.get("message", "Product details are unavailable.")
        product = result.get("product", {})
        lines = [f"{product.get('name', 'Product')} — {product.get('description') or 'No description available.'}"]
        rating = product.get("rating", {})
        lines.append(f"Rating: {rating.get('weighted')} ({rating.get('count')} reviews)")
        lines.append("Variants:")
        for variant in result.get("variants", []):
            attributes = ", ".join(f"{key}={value}" for key, value in variant.get("attributes", {}).items()) or "standard"
            lines.append(f"- variant #{variant['id']} · {attributes} · ₹{variant['price']} · stock {variant['stock_qty']} ({variant['stock_status']})")
        lines.append("Add a choice with: add product <id> variant <id> quantity <n>.")
        return "\n".join(lines)

    async def checkout(self, customer_id: int) -> str:
        """Create one bounded order/payment link per selected cart line."""
        items = self.store.cart_items(customer_id)
        if not items:
            return "Your cart is empty."
        created: list[dict[str, Any]] = []
        failed: list[str] = []
        for item in items:
            result = await self.client.call(
                "create_order",
                {
                    "request": {
                        "customer_id": customer_id,
                        **item,
                        "reasoning": "Customer selected this item from the product cards and cart.",
                    }
                },
            )
            if result.get("error"):
                failed.append(f"product #{item['product_id']} / variant #{item['variant_id']}: {result.get('message', 'could not be ordered')}")
                continue
            created.append(result)
            self.store.save_pending_order(customer_id, order_id=result["order_id"], amount=result["amount"], payment_link=result["payment_link"], status=result["status"])
            self.store.remove_cart_item(customer_id, product_id=item["product_id"], variant_id=item["variant_id"])
        lines: list[str] = []
        if created:
            lines.append(f"Created {len(created)} order(s) from your cart:")
            for result in created:
                lines.append(f"Order #{result['order_id']} — ₹{result['amount']} — pay here: {result['payment_link']}")
            lines.append("Each cart line has its own payment link; stock is finalized only after the verified webhook.")
        if failed:
            lines.append("Some cart lines were not created and remain in the cart:")
            lines.extend(f"- {message}" for message in failed)
        return "\n".join(lines) if lines else "No cart orders were created."

    async def confirm_purchase(self, customer_id: int) -> str:
        if self.store.cart_items(customer_id):
            return await self.checkout(customer_id)
        action = self.store.pending_action(customer_id)
        if not action or action.get("action_type") != "create_order":
            return "There is no purchase waiting for confirmation."
        result = await self.client.call("create_order", {"request": action["payload"]})
        if result.get("error"):
            self.store.clear_pending_action(customer_id)
            return result.get("message", "The order could not be created.")
        self.store.clear_pending_action(customer_id)
        self.store.save_pending_order(customer_id, order_id=result["order_id"], amount=result["amount"], payment_link=result["payment_link"], status=result["status"])
        return f"Order #{result['order_id']} is awaiting payment for ₹{result['amount']}. Open this Razorpay test-mode link: {result['payment_link']}\nI will only call it paid after Razorpay's verified webhook."

    async def poll(self, customer_id: int, order_id: int | None = None) -> str:
        orders = self.store.pending_orders(customer_id)
        if order_id is None:
            if not orders:
                return "You have no pending orders."
            order_ids = [int(order["order_id"]) for order in orders]
        else:
            order_ids = [order_id]
        lines = []
        for current_order_id in order_ids:
            result = await self.client.call("get_order_status", {"order_id": current_order_id})
            if result.get("status") in {"paid", "failed"}:
                self.store.update_pending_status(customer_id, current_order_id, result["status"])
            lines.append(f"Order #{current_order_id}: {result.get('status', result.get('message', 'unknown'))}. {result.get('message', '')}".strip())
        return "\n".join(lines)

    async def handle(self, customer_id: int, text: str) -> str:
        self.store.append_message(customer_id, "user", text)
        lowered = text.lower().strip()
        if lowered in {"confirm", "yes", "confirm order", "confirm payment"}:
            response = await self.confirm_purchase(customer_id)
        elif lowered in {"cart", "show cart", "view cart"}:
            response = await self.show_cart(customer_id)
        elif lowered.startswith("details") or lowered.startswith("show details"):
            response = await self.product_details(customer_id, text)
        elif lowered.startswith("add") or lowered.startswith("select") or lowered.startswith("buy") or lowered.startswith("order") or "purchase product" in lowered:
            response = await self.prepare_purchase(customer_id, text)
        elif "status" in lowered or "paid" in lowered:
            match = re.search(r"(?:order\s*)#?\s*(\d+)", lowered)
            response = await self.poll(customer_id, int(match.group(1)) if match else None)
        else:
            response = await self.search(customer_id, text)
        self.store.append_message(customer_id, "assistant", response)
        return response


async def cli() -> None:
    customer_id = int(os.getenv("CUSTOMER_ID", "1"))
    agent = CommerceAgent(ACPClient(os.getenv("ACP_MCP_URL", "http://127.0.0.1:8000/mcp")))
    await agent.start()
    print("RZR-Handshake client agent ready. Type 'quit' to exit.")
    while True:
        try:
            text = input("you> ").strip()
        except EOFError:
            break
        if text.lower() in {"quit", "exit"}:
            break
        if text:
            try:
                print(f"agent> {await agent.handle(customer_id, text)}")
            except Exception as exc:  # keep a CLI transport failure readable
                print(f"agent> ACP request failed: {exc}")


if __name__ == "__main__":
    asyncio.run(cli())
