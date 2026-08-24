from __future__ import annotations

from sqlalchemy import select

from ..audit.logger import audit, tool_call
from ..db import Order, Product, Variant, session_scope
from ..models import OrderStatusResponse


async def get_order_status(order_id: int, *, actor: str = "agent") -> OrderStatusResponse | dict:
    async with session_scope() as session:
        tool_call(session, tool_name="get_order_status", actor=actor, details={"order_id": order_id})
        row = (await session.execute(select(Order, Variant, Product).join(Variant, Order.variant_id == Variant.id).join(Product, Variant.product_id == Product.id).where(Order.id == order_id))).first()
        if row is None:
            audit(session, actor=actor, event_type="order_not_found", entity_type="order", entity_id=order_id)
            await session.commit()
            return {"error": "not_found", "message": "Order not found."}
        order, _variant, product = row
        message = None
        if order.status == "awaiting_payment":
            message = "Payment is not verified yet. The payment link remains pending."
        elif order.status == "paid":
            message = "Payment verified and inventory reserved for this order."
        elif order.status == "failed":
            message = "This sold out right before your payment cleared; a refund is required."
        await session.commit()
        return OrderStatusResponse(
            order_id=order.id,
            status=order.status,
            amount=order.total_amount,
            product_name=product.name,
            quantity=order.quantity,
            paid_at=order.paid_at.isoformat() if order.paid_at else None,
            message=message,
        )
