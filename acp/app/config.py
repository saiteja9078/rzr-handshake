"""Small, dependency-light application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


def _decimal_env(name: str, default: str) -> Decimal:
    try:
        return Decimal(os.getenv(name, default))
    except Exception as exc:  # pragma: no cover - startup configuration error
        raise ValueError(f"{name} must be a decimal number") from exc


@dataclass(frozen=True)
class Settings:
    # PostgreSQL is the deployment default documented in README. SQLite keeps a
    # zero-setup local demo and is also used by the test suite.
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./acp_demo.db")
    razorpay_key_id: str | None = os.getenv("RAZORPAY_KEY_ID")
    razorpay_key_secret: str | None = os.getenv("RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str | None = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    payment_provider: str = os.getenv("PAYMENT_PROVIDER", "auto")
    max_qty: int = int(os.getenv("MAX_QTY", "10"))
    max_spend: Decimal = _decimal_env("MAX_SPEND", "100000.00")
    reviews_page_size: int = int(os.getenv("REVIEWS_PAGE_SIZE", "5"))
    catalog_page_size: int = int(os.getenv("CATALOG_PAGE_SIZE", "10"))
    catalog_max_page_size: int = int(os.getenv("CATALOG_MAX_PAGE_SIZE", "100"))


settings = Settings()
