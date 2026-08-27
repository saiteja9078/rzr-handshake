"""Durable, auth-lite client-side conversation and purchase state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionStore:
    def __init__(self, path: str | Path = "./client-agent/session.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversation_customer ON conversation(customer_id);
                CREATE TABLE IF NOT EXISTS pending_orders (
                    customer_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL,
                    amount TEXT NOT NULL,
                    payment_link TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(customer_id, order_id)
                );
                CREATE TABLE IF NOT EXISTS pending_actions (
                    customer_id INTEGER PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cart_items (
                    customer_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    variant_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(customer_id, product_id, variant_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def append_message(self, customer_id: int, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO conversation(customer_id, role, content, created_at) VALUES (?, ?, ?, ?)", (customer_id, role, content, self._now()))

    def history(self, customer_id: int, limit: int = 50) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT role, content, created_at FROM conversation WHERE customer_id = ? ORDER BY id DESC LIMIT ?", (customer_id, limit)).fetchall()
        return [{"role": row[0], "content": row[1], "created_at": row[2]} for row in reversed(rows)]

    def save_pending_order(self, customer_id: int, *, order_id: int, amount: Any, payment_link: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_orders(customer_id, order_id, amount, payment_link, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(customer_id, order_id) DO UPDATE SET amount=excluded.amount, payment_link=excluded.payment_link, status=excluded.status, updated_at=excluded.updated_at""",
                (customer_id, order_id, str(amount), payment_link, status, self._now()),
            )

    def pending_orders(self, customer_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT order_id, amount, payment_link, status, updated_at FROM pending_orders WHERE customer_id = ? ORDER BY updated_at DESC", (customer_id,)).fetchall()
        return [{"order_id": row[0], "amount": row[1], "payment_link": row[2], "status": row[3], "updated_at": row[4]} for row in rows]

    def update_pending_status(self, customer_id: int, order_id: int, status: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE pending_orders SET status = ?, updated_at = ? WHERE customer_id = ? AND order_id = ?", (status, self._now(), customer_id, order_id))

    def save_pending_action(self, customer_id: int, action_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_actions(customer_id, action_type, payload, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(customer_id) DO UPDATE SET action_type=excluded.action_type, payload=excluded.payload, updated_at=excluded.updated_at""",
                (customer_id, action_type, json.dumps(payload), self._now()),
            )

    def pending_action(self, customer_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT action_type, payload, updated_at FROM pending_actions WHERE customer_id = ?", (customer_id,)).fetchone()
        if not row:
            return None
        return {"action_type": row[0], "payload": json.loads(row[1]), "updated_at": row[2]}

    def clear_pending_action(self, customer_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM pending_actions WHERE customer_id = ?", (customer_id,))

    def add_cart_item(self, customer_id: int, *, product_id: int, variant_id: int, quantity: int) -> int:
        """Add to the durable cart and return the resulting line quantity."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT quantity FROM cart_items WHERE customer_id = ? AND product_id = ? AND variant_id = ?",
                (customer_id, product_id, variant_id),
            ).fetchone()
            new_quantity = (int(row[0]) if row else 0) + quantity
            connection.execute(
                """INSERT INTO cart_items(customer_id, product_id, variant_id, quantity, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(customer_id, product_id, variant_id)
                   DO UPDATE SET quantity=excluded.quantity, updated_at=excluded.updated_at""",
                (customer_id, product_id, variant_id, new_quantity, self._now()),
            )
        return new_quantity

    def cart_items(self, customer_id: int) -> list[dict[str, int]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT product_id, variant_id, quantity FROM cart_items WHERE customer_id = ? ORDER BY updated_at, product_id, variant_id",
                (customer_id,),
            ).fetchall()
        return [{"product_id": row[0], "variant_id": row[1], "quantity": row[2]} for row in rows]

    def remove_cart_item(self, customer_id: int, *, product_id: int, variant_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM cart_items WHERE customer_id = ? AND product_id = ? AND variant_id = ?",
                (customer_id, product_id, variant_id),
            )

    def clear_cart(self, customer_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cart_items WHERE customer_id = ?", (customer_id,))
