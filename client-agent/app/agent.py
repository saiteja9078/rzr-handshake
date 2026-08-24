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

    def filters(self, text: str) -> dict[str, Any]:
        lowered = text.lower()
        categories = self.schema.get("categories", [])
        category = next((value for value in categories if value.lower() in lowered), None)
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
        known_values = {"color": ["red", "blue", "black", "white", "green"], "size": ["xs", "s", "m", "l", "xl", "small", "medium", "large"], "storage": ["64gb", "128gb", "256gb", "512gb"]}
        for attribute in self.schema.get("attributes_by_category", {}).get(category, []) if category else []:
            for value in known_values.get(attribute, []):
                if re.search(rf"\b{re.escape(value)}\b", lowered):
                    attributes[attribute] = value
                    break
            explicit = re.search(rf"{re.escape(attribute)}\s*[:=]?\s*([\w-]+)", lowered)
            if explicit:
                attributes[attribute] = explicit.group(1)
        return {"category": category, "min_price": minimum, "max_price": maximum, "min_rating": rating_match.group(1) if rating_match else None, "attributes": attributes, "keyword": None if category else text, "sort_by": sort_by, "page": 1}


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
        filters = {key: value for key, value in raw_filters.items() if value is not None and value != {}}
        result = await self.client.call("search_catalog", {"filters": filters})
        self.store.append_message(customer_id, "assistant", str(result))
        products = result.get("products", [])
        if not products:
            return "I couldn't find a matching product."
        lines = [f"Found {result.get('total_results', len(products))} result(s):"]
        for item in products:
            rating = item.get("rating", {})
            lines.append(f"#{item['id']} {item['name']} — ₹{item['price']} — weighted rating {rating.get('weighted')} ({rating.get('count')} reviews) — {item['stock_status']}")
        lines.append("Ask for details, or say 'buy product <id> variant <id> quantity <n>'.")
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
        amount = (Decimal(str(variant["price"])) * quantity).quantize(Decimal("0.01"))
        self.store.save_pending_action(customer_id, "create_order", {"customer_id": customer_id, "product_id": product_id, "variant_id": variant_id, "quantity": quantity, "reasoning": "Customer selected the variant after catalog details were shown."})
        return f"{details['product']['name']} / variant {variant_id}, quantity {quantity}, is ₹{amount}. Stock currently shows {variant['stock_qty']}. Reply 'confirm' to create the Razorpay payment link."

    async def confirm_purchase(self, customer_id: int) -> str:
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
            order_id = int(orders[0]["order_id"])
        result = await self.client.call("get_order_status", {"order_id": order_id})
        if result.get("status") in {"paid", "failed"}:
            self.store.update_pending_status(customer_id, order_id, result["status"])
        return f"Order #{order_id}: {result.get('status', result.get('message', 'unknown'))}. {result.get('message', '')}".strip()

    async def handle(self, customer_id: int, text: str) -> str:
        self.store.append_message(customer_id, "user", text)
        lowered = text.lower().strip()
        if lowered in {"confirm", "yes", "confirm order", "confirm payment"}:
            response = await self.confirm_purchase(customer_id)
        elif lowered.startswith("buy") or lowered.startswith("order") or "purchase product" in lowered:
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
