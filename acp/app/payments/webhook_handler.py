"""Plain Razorpay webhook route. It is intentionally not an MCP tool."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy import select

from ..audit.logger import audit
from ..db import Order, Payment, Variant, session_scope
from ..models import WebhookResponse
from .razorpay_client import amount_to_paise, verify_webhook_signature

router = APIRouter(tags=["payments"])


async def _audit_rejected_webhook(event_type: str, details: dict[str, Any]) -> None:
    async with session_scope() as session:
        audit(session, actor="webhook", event_type=event_type, details=details)
        await session.commit()


def _nested(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def extract_payment_event(payload: dict[str, Any]) -> tuple[str | None, str | None, int | None, str | None, str | None]:
    link_id = payload.get("payment_link_id") or _nested(payload, "payload", "payment_link", "entity", "id") or _nested(payload, "payment_link", "entity", "id")
    payment_id = payload.get("payment_id") or _nested(payload, "payload", "payment", "entity", "id") or _nested(payload, "payment", "entity", "id")
    amount = payload.get("amount") or _nested(payload, "payload", "payment_link", "entity", "amount") or _nested(payload, "payload", "payment", "entity", "amount")
    event_name = payload.get("event")
    payment_status = _nested(payload, "payload", "payment_link", "entity", "status") or _nested(payload, "payload", "payment", "entity", "status")
    try:
        parsed_amount = int(amount) if amount is not None else None
    except (TypeError, ValueError):
        parsed_amount = None
    return (str(link_id) if link_id else None, str(payment_id) if payment_id else None, parsed_amount, str(event_name) if event_name else None, str(payment_status) if payment_status else None)


def _is_success_event(event_name: str | None, payment_status: str | None) -> bool:
    if event_name and event_name.lower() not in {"payment_link.paid", "payment.captured", "payment_link.paid.v1"}:
        return False
    if payment_status and payment_status.lower() not in {"paid", "captured", "success"}:
        return False
    return True


@router.post("/webhooks/razorpay", response_model=WebhookResponse)
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature")) -> WebhookResponse | Response:
    raw_body = await request.body()
    if not verify_webhook_signature(raw_body, x_razorpay_signature):
        await _audit_rejected_webhook("webhook_signature_rejected", {"body_sha256": hashlib.sha256(raw_body).hexdigest()})
        return Response(content=json.dumps({"error": "invalid_signature", "message": "Webhook signature verification failed."}), status_code=status.HTTP_401_UNAUTHORIZED, media_type="application/json")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        await _audit_rejected_webhook("webhook_payload_rejected", {"reason": "invalid_json"})
        return Response(content=json.dumps({"error": "invalid_payload", "message": "Webhook body is not valid JSON."}), status_code=status.HTTP_400_BAD_REQUEST, media_type="application/json")

    link_id, payment_id, event_amount_paise, event_name, payment_status = extract_payment_event(payload)
    if not link_id:
        await _audit_rejected_webhook("webhook_payload_rejected", {"reason": "missing_payment_link"})
        return Response(content=json.dumps({"error": "missing_payment_link", "message": "The webhook did not identify a payment link."}), status_code=status.HTTP_400_BAD_REQUEST, media_type="application/json")

    if not _is_success_event(event_name, payment_status):
        await _audit_rejected_webhook("payment_event_not_successful", {"payment_link_id": link_id, "event": event_name, "status": payment_status})
        return WebhookResponse(ok=True, status="awaiting_payment", message="The signed webhook was not a successful payment event; the order remains awaiting payment.")

    async with session_scope() as session:
        order = await session.scalar(select(Order).where(Order.razorpay_payment_link_id == link_id).with_for_update())
        if order is None:
            audit(session, actor="webhook", event_type="payment_order_not_found", details={"payment_link_id": link_id, "payload": payload})
            await session.commit()
            return Response(content=json.dumps({"error": "order_not_found", "message": "No order is linked to this payment link."}), status_code=status.HTTP_404_NOT_FOUND, media_type="application/json")

        expected_paise = amount_to_paise(Decimal(str(order.total_amount)))
        if event_amount_paise is not None and event_amount_paise != expected_paise:
            audit(session, actor="webhook", event_type="payment_amount_mismatch", entity_type="order", entity_id=order.id, details={"expected_paise": expected_paise, "received_paise": event_amount_paise, "payment_link_id": link_id})
            await session.commit()
            return Response(content=json.dumps({"error": "amount_mismatch", "message": "Payment amount did not match the locked order amount."}), status_code=status.HTTP_400_BAD_REQUEST, media_type="application/json")

        if order.status in {"paid", "failed"}:
            audit(session, actor="webhook", event_type="duplicate_webhook", entity_type="order", entity_id=order.id, details={"status": order.status, "payment_id": payment_id})
            await session.commit()
            return WebhookResponse(ok=True, order_id=order.id, status=order.status, message="Webhook was already processed.")

        # Lock the inventory row, not just the order. Two different orders for
        # the same last unit therefore serialize at this exact point.
        variant = await session.scalar(select(Variant).where(Variant.id == order.variant_id).with_for_update())
        if variant is None:
            order.status = "failed"
            payment_status = "refund_required"
            event_type = "stock_depleted_post_payment"
            message = "This sold out right before your payment cleared; a refund is required."
        elif variant.stock_qty >= order.quantity:
            variant.stock_qty -= order.quantity
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            payment_status = "success"
            event_type = "payment_verified"
            message = "Payment verified and stock reserved."
        else:
            order.status = "failed"
            payment_status = "refund_required"
            event_type = "stock_depleted_post_payment"
            message = "This sold out right before your payment cleared; a refund is required."

        payment = Payment(
            order_id=order.id,
            razorpay_payment_id=payment_id,
            razorpay_signature=x_razorpay_signature,
            verified=True,
            status=payment_status,
            amount=order.total_amount,
            raw_webhook_payload=payload,
        )
        session.add(payment)
        audit(session, actor="webhook", event_type=event_type, entity_type="order", entity_id=order.id, details={"payment_id": payment_id, "payment_link_id": link_id, "quantity": order.quantity, "remaining_stock": variant.stock_qty if variant else None, "refund_required": payment_status == "refund_required"})
        await session.commit()
        return WebhookResponse(ok=True, order_id=order.id, status=order.status, message=message)
