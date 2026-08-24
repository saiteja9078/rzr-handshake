"""Razorpay Payment Links adapter with a deterministic local demo provider."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Protocol

from ..config import settings


def amount_to_paise(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class PaymentLinkClient(Protocol):
    async def create_payment_link(
        self,
        *,
        amount: Decimal,
        description: str,
        customer_id: int,
        product_id: int,
        variant_id: int,
        quantity: int,
    ) -> dict[str, Any]: ...


class DemoPaymentClient:
    """Local provider used when Razorpay keys are absent.

    It creates a recognizable payment-link-shaped value; it does not move money.
    The webhook endpoint can still be exercised with the configured demo secret.
    """

    async def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
        link_id = f"plink_demo_{uuid.uuid4().hex[:16]}"
        return {
            "id": link_id,
            "short_url": f"https://rzp.io/i/{link_id[-10:]}",
            "amount": amount_to_paise(kwargs["amount"]),
            "currency": "INR",
        }


class RazorpayPaymentClient:
    def __init__(self, key_id: str, key_secret: str) -> None:
        import razorpay

        self._client = razorpay.Client(auth=(key_id, key_secret))

    async def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "amount": amount_to_paise(kwargs["amount"]),
            "currency": "INR",
            "accept_partial": False,
            "description": kwargs["description"],
            "customer": {"name": f"Customer {kwargs['customer_id']}"},
            "notify": {"sms": False, "email": False},
            "reminder_enable": True,
            "notes": {
                "customer_id": str(kwargs["customer_id"]),
                "product_id": str(kwargs["product_id"]),
                "variant_id": str(kwargs["variant_id"]),
                "quantity": str(kwargs["quantity"]),
            },
        }
        # The official SDK is synchronous; run it in the worker thread so the
        # async FastAPI event loop is never blocked by network I/O.
        import asyncio

        return await asyncio.to_thread(self._client.payment_link.create, payload)


def get_payment_client() -> PaymentLinkClient:
    provider = settings.payment_provider.lower()
    if provider == "demo" or not (settings.razorpay_key_id and settings.razorpay_key_secret):
        return DemoPaymentClient()
    if provider not in {"auto", "razorpay"}:
        raise ValueError(f"Unsupported PAYMENT_PROVIDER={settings.payment_provider}")
    return RazorpayPaymentClient(settings.razorpay_key_id, settings.razorpay_key_secret)


def webhook_secret() -> str:
    return settings.razorpay_webhook_secret or settings.razorpay_key_secret or "demo-webhook-secret"


def verify_webhook_signature(raw_body: bytes, signature: str | None, secret: str | None = None) -> bool:
    if not signature:
        return False
    expected = hmac.new((secret or webhook_secret()).encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
