from __future__ import annotations

import hashlib
import hmac
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Configure the test database before importing ACP modules, because the engine
# is intentionally created once at application import time.
TEST_DB = Path(__file__).with_name("test_acp.sqlite3")
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["PAYMENT_PROVIDER"] = "demo"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test-webhook-secret"

from acp.app.db import AuditLog, Base, Customer, Merchant, Order, Payment, Product, Review, SessionLocal, Variant, engine, init_db
from acp.app.main import app
from acp.app.models import CreateOrderInput, SearchFilters, SubmitReviewInput
from acp.app.payments.razorpay_client import DemoPaymentClient
from acp.app.payments.webhook_handler import razorpay_webhook
from acp.app.tools.create_order import create_order
from acp.app.tools.get_catalog_schema import get_catalog_schema
from acp.app.tools.get_order_status import get_order_status
from acp.app.tools.search_catalog import search_catalog
from acp.app.tools.submit_review import submit_review


@pytest_asyncio.fixture
async def db_setup():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        merchant = Merchant(name="Demo Merchant")
        customer = Customer(name="Test Buyer", email="buyer@example.com")
        product = Product(merchant=merchant, name="RZR Runner", brand="Handshake", category="shoes", description="A test shoe", rating_avg=Decimal("0.0"), rating_count=0, bayesian_rating=Decimal("0.0"))
        session.add_all([merchant, customer, product])
        await session.flush()
        scarce = Variant(product_id=product.id, attributes={"color": "red", "size": "m"}, price=Decimal("1200.00"), mrp=Decimal("1500.00"), stock_qty=1)
        roomy = Variant(product_id=product.id, attributes={"color": "blue", "size": "l"}, price=Decimal("900.00"), mrp=Decimal("1000.00"), stock_qty=8)
        session.add_all([scarce, roomy])
        await session.commit()
        ids = {"customer": customer.id, "product": product.id, "scarce": scarce.id, "roomy": roomy.id}
    yield ids


class FakePaymentClient(DemoPaymentClient):
    def __init__(self) -> None:
        self.calls = []

    async def create_payment_link(self, **kwargs):
        self.calls.append(kwargs)
        return await super().create_payment_link(**kwargs)


@pytest.mark.asyncio
async def test_schema_search_and_server_side_bounds(db_setup):
    schema = await get_catalog_schema()
    assert "shoes" in schema.categories
    assert "color" in schema.attributes_by_category["shoes"]
    assert "red" in schema.attribute_values_by_category["shoes"]["color"]
    results = await search_catalog(SearchFilters(category="shoes", attributes={"color": "red"}))
    assert results.total_results == 1
    assert results.products[0].discount_pct == Decimal("20.00")

    client = FakePaymentClient()
    rejected = await create_order(CreateOrderInput(customer_id=db_setup["customer"], product_id=db_setup["product"], variant_id=db_setup["roomy"], quantity=11), payment_client=client)
    assert rejected.error == "exceeds_bounds"
    assert not client.calls


@pytest.mark.asyncio
async def test_catalog_result_count_and_pagination(db_setup):
    async with SessionLocal() as session:
        base = await session.get(Product, db_setup["product"])
        extra_one = Product(merchant_id=base.merchant_id, name="RZR Sprint", brand="Handshake", category="shoes", description="A second test shoe", rating_avg=Decimal("4.0"), rating_count=10, bayesian_rating=Decimal("3.8"))
        extra_two = Product(merchant_id=base.merchant_id, name="RZR Trail", brand="Handshake", category="shoes", description="A third test shoe", rating_avg=Decimal("4.5"), rating_count=20, bayesian_rating=Decimal("4.2"))
        session.add_all([extra_one, extra_two])
        await session.flush()
        session.add_all([
            Variant(product_id=extra_one.id, attributes={"color": "black"}, price=Decimal("800.00"), stock_qty=4),
            Variant(product_id=extra_two.id, attributes={"color": "green"}, price=Decimal("1500.00"), stock_qty=4),
        ])
        await session.commit()

    first_page = await search_catalog(SearchFilters(category="shoes", limit=1))
    assert first_page.total_results == 3
    assert len(first_page.products) == 1
    assert first_page.has_more is True
    assert first_page.next_page == 2

    second_page = await search_catalog(SearchFilters(category="shoes", limit=1, page=2))
    assert len(second_page.products) == 1
    assert second_page.products[0].id != first_page.products[0].id


@pytest.mark.asyncio
async def test_payment_is_webhook_gated_and_review_requires_paid_order(db_setup):
    client = FakePaymentClient()
    request = CreateOrderInput(customer_id=db_setup["customer"], product_id=db_setup["product"], variant_id=db_setup["roomy"], quantity=2, reasoning="blue shoe under budget")
    created = await create_order(request, payment_client=client)
    assert created.status == "awaiting_payment"

    before = await get_order_status(created.order_id)
    assert before.status == "awaiting_payment"

    early_review = await submit_review(SubmitReviewInput(customer_id=db_setup["customer"], product_id=db_setup["product"], order_id=created.order_id, rating=5, text="Too early"))
    assert early_review.error == "not_purchased"

    payload = {"payment_link_id": client.calls[0]["description"].replace(" ", "-"), "payment_id": "pay_test_1"}
    # Use the actual link ID stored by the demo client; its description is only
    # used above to prove the provider was called, so fetch the order row here.
    async with SessionLocal() as session:
        order = await session.get(Order, created.order_id)
        payload["payment_link_id"] = order.razorpay_payment_link_id
    raw = json.dumps(payload).encode()
    signature = hmac.new(b"test-webhook-secret", raw, hashlib.sha256).hexdigest()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": signature})
    assert response.status_code == 200
    assert response.json()["status"] == "paid"

    paid = await get_order_status(created.order_id)
    assert paid.status == "paid"
    review = await submit_review(SubmitReviewInput(customer_id=db_setup["customer"], product_id=db_setup["product"], order_id=created.order_id, rating=5, text="Great"))
    assert review.sentiment == "positive"
    duplicate = await submit_review(SubmitReviewInput(customer_id=db_setup["customer"], product_id=db_setup["product"], order_id=created.order_id, rating=4, text="Again"))
    assert duplicate.error == "already_reviewed"


@pytest.mark.asyncio
async def test_last_unit_failure_is_explicit_and_audited(db_setup):
    client = FakePaymentClient()
    first = await create_order(CreateOrderInput(customer_id=db_setup["customer"], product_id=db_setup["product"], variant_id=db_setup["scarce"], quantity=1), payment_client=client)
    second = await create_order(CreateOrderInput(customer_id=db_setup["customer"], product_id=db_setup["product"], variant_id=db_setup["scarce"], quantity=1), payment_client=client)
    assert first.status == second.status == "awaiting_payment"

    async with SessionLocal() as session:
        first_order = await session.get(Order, first.order_id)
        second_order = await session.get(Order, second.order_id)
        first_link = first_order.razorpay_payment_link_id
        second_link = second_order.razorpay_payment_link_id

    async def complete(link: str, payment_id: str):
        payload = json.dumps({"payment_link_id": link, "payment_id": payment_id}).encode()
        sig = hmac.new(b"test-webhook-secret", payload, hashlib.sha256).hexdigest()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            return await http.post("/webhooks/razorpay", content=payload, headers={"X-Razorpay-Signature": sig})

    winner = await complete(first_link, "pay_winner")
    loser = await complete(second_link, "pay_loser")
    assert winner.json()["status"] == "paid"
    assert loser.json()["status"] == "failed"
    assert "sold out" in loser.json()["message"]

    async with SessionLocal() as session:
        failed_payment = await session.scalar(select_payment_for_order(second.order_id))
        events = (await session.scalars(select_audit_event("stock_depleted_post_payment"))).all()
        variant = await session.get(Variant, db_setup["scarce"])
        assert failed_payment.status == "refund_required"
        assert len(events) >= 1
        assert variant.stock_qty == 0


def select_payment_for_order(order_id: int):
    from sqlalchemy import select

    return select(Payment).where(Payment.order_id == order_id)


def select_audit_event(event_type: str):
    from sqlalchemy import select

    return select(AuditLog).where(AuditLog.event_type == event_type)


@pytest.mark.asyncio
async def test_invalid_webhook_signature_is_rejected(db_setup):
    raw = b'{"payment_link_id":"anything"}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": "bad"})
    assert response.status_code == 401
