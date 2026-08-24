from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..audit.logger import audit, tool_call
from ..bounds.policy import check_order_bounds
from ..db import Customer, Order, Product, Variant, session_scope
from ..models import CreateOrderInput, CreateOrderResponse, ToolError
from ..payments.razorpay_client import PaymentLinkClient, get_payment_client


def _error(error: str, message: str, *, limit: int | str | None = None, requested: int | str | None = None) -> ToolError:
    return ToolError(error=error, message=message, limit=limit, requested=requested)


async def create_order(
    request: CreateOrderInput,
    *,
    payment_client: PaymentLinkClient | None = None,
    actor: str | None = None,
) -> CreateOrderResponse | ToolError:
    actor = actor or f"customer:{request.customer_id}"
    async with session_scope() as session:
        tool_call(session, tool_name="create_order", actor=actor, details=request.model_dump(mode="json"))
        customer = await session.get(Customer, request.customer_id)
        if customer is None:
            audit(session, actor=actor, event_type="order_rejected", details={"reason": "customer_not_found", "customer_id": request.customer_id})
            await session.commit()
            return _error("customer_not_found", "Customer account was not found.")

        product = await session.get(Product, request.product_id)
        variant = await session.get(Variant, request.variant_id)
        if product is None or variant is None or variant.product_id != request.product_id:
            audit(session, actor=actor, event_type="order_rejected", details={"reason": "variant_not_found", "product_id": request.product_id, "variant_id": request.variant_id})
            await session.commit()
            return _error("variant_not_found", "The selected variant does not belong to this product.")

        unit_price = Decimal(str(variant.price))
        total = (unit_price * request.quantity).quantize(Decimal("0.01"))
        violation = check_order_bounds(request.quantity, total)
        if violation:
            audit(session, actor=actor, event_type="bound_check_failed", entity_type="variant", entity_id=variant.id, details={"error": violation.error, "limit": violation.limit, "requested": violation.requested, "quantity": request.quantity, "total": str(total)})
            await session.commit()
            return _error(violation.error, violation.message, limit=violation.limit, requested=violation.requested)

        if variant.stock_qty < request.quantity:
            audit(session, actor=actor, event_type="order_rejected", entity_type="variant", entity_id=variant.id, details={"reason": "insufficient_stock", "available": variant.stock_qty, "requested": request.quantity})
            await session.commit()
            return _error("insufficient_stock", f"Only {variant.stock_qty} unit(s) are available right now.", limit=variant.stock_qty, requested=request.quantity)

        provider = payment_client or get_payment_client()
        try:
            payment_link = await provider.create_payment_link(
                amount=total,
                description=f"{product.name} x {request.quantity}",
                customer_id=request.customer_id,
                product_id=request.product_id,
                variant_id=request.variant_id,
                quantity=request.quantity,
            )
        except Exception as exc:
            audit(session, actor=actor, event_type="payment_link_failed", entity_type="product", entity_id=product.id, details={"error": str(exc)[:500], "amount": str(total)})
            await session.commit()
            return _error("payment_link_unavailable", "The payment link could not be created. No order was placed.")

        link_id = payment_link.get("id")
        link_url = payment_link.get("short_url") or payment_link.get("short_link")
        if not link_id or not link_url:
            audit(session, actor=actor, event_type="payment_link_failed", entity_type="product", entity_id=product.id, details={"reason": "provider_missing_link_fields", "response": {str(k): str(v) for k, v in payment_link.items()}})
            await session.commit()
            return _error("payment_link_unavailable", "The payment provider returned an invalid payment link. No order was placed.")

        # Inventory is deliberately not decremented here. The verified webhook
        # owns the money-to-stock transition and locks the variant row again.
        order = Order(
            customer_id=request.customer_id,
            variant_id=request.variant_id,
            quantity=request.quantity,
            unit_price=unit_price,
            total_amount=total,
            status="awaiting_payment",
            razorpay_payment_link_id=link_id,
        )
        session.add(order)
        await session.flush()
        audit(
            session,
            actor=actor,
            event_type="order_created",
            entity_type="order",
            entity_id=order.id,
            details={
                "product_id": request.product_id,
                "variant_id": request.variant_id,
                "quantity": request.quantity,
                "unit_price": str(unit_price),
                "total_amount": str(total),
                "reasoning": request.reasoning,
                "search_filters": request.search_filters,
            },
        )
        await session.commit()
        return CreateOrderResponse(order_id=order.id, amount=total, payment_link=link_url, status="awaiting_payment")
