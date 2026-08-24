"""Structured, queryable audit log helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AuditLog


def audit(
    session: AsyncSession,
    *,
    actor: str,
    event_type: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        actor=actor,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    session.add(row)
    return row


def tool_call(
    session: AsyncSession,
    *,
    tool_name: str,
    actor: str = "agent",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    return audit(
        session,
        actor=actor,
        event_type="tool_call",
        entity_type="tool",
        details={"tool": tool_name, **(details or {})},
    )
