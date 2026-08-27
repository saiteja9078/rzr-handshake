from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "client-agent"))

from app.agent import RuleBasedIntentParser
from app.session_store import SessionStore


def test_dynamic_query_parser_extracts_count_and_catalog_value():
    parser = RuleBasedIntentParser(
        {
            "categories": ["shoes"],
            "attributes_by_category": {"shoes": ["color"]},
            "attribute_values_by_category": {"shoes": {"color": ["red", "blue"]}},
        }
    )
    filters = parser.filters("show me 2 red shoes under 5000")
    assert filters["requested_count"] == 2
    assert filters["limit"] == 2
    assert filters["attributes"] == {"color": "red"}
    assert filters["max_price"] == "5000"


def test_cart_is_durable_and_accumulates_duplicate_lines(tmp_path):
    store = SessionStore(tmp_path / "session.sqlite3")
    assert store.add_cart_item(1, product_id=10, variant_id=20, quantity=1) == 1
    assert store.add_cart_item(1, product_id=10, variant_id=20, quantity=2) == 3
    assert store.add_cart_item(1, product_id=11, variant_id=21, quantity=1) == 1
    assert store.cart_items(1) == [
        {"product_id": 10, "variant_id": 20, "quantity": 3},
        {"product_id": 11, "variant_id": 21, "quantity": 1},
    ]
    store.remove_cart_item(1, product_id=10, variant_id=20)
    assert store.cart_items(1) == [{"product_id": 11, "variant_id": 21, "quantity": 1}]
