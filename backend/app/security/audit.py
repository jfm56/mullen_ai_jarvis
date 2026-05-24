"""Append-only audit log.

Every agent action, integration call, and approval decision is recorded
here. The `audit_log` table has a Postgres trigger that blocks UPDATE
and DELETE — the table can only grow.

Sensitive payloads are stored as 16-char hashes, not in plaintext, so
the audit log itself is not a leak vector.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker
from app.db.models import AuditLog

logger = logging.getLogger("jarvis.audit")


@dataclass(frozen=True)
class AuditRow:
    timestamp: datetime
    agent: str
    domain: str
    action_class: str
    action_name: str
    target_summary: str
    decision: str
    input_hash: str = ""
    output_hash: str = ""
    integration: str = ""
    latency_ms: int = 0
    user_id: uuid.UUID | None = None
    request_id: str = ""
    approval_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def hash_payload(payload: Any) -> str:
    """Stable short hash for traceability without storing the payload."""
    encoded = repr(payload).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()[:16]


async def _persist(row: AuditRow, *, session: AsyncSession | None = None) -> None:
    record = AuditLog(
        timestamp=row.timestamp,
        agent=row.agent,
        domain=row.domain,
        action_class=row.action_class,
        action_name=row.action_name,
        target_summary=row.target_summary,
        decision=row.decision,
        integration=row.integration,
        latency_ms=row.latency_ms,
        input_hash=row.input_hash,
        output_hash=row.output_hash,
        user_id=row.user_id,
        request_id=row.request_id,
        approval_id=row.approval_id,
        extra=row.extra or {},
    )
    if session is not None:
        session.add(record)
        return
    async with get_sessionmaker()() as owned:
        owned.add(record)
        await owned.commit()


async def emit(
    *,
    agent: str,
    domain: str,
    action_class: str,
    action_name: str,
    target_summary: str,
    decision: str,
    integration: str = "",
    latency_ms: int = 0,
    input_payload: Any = None,
    output_payload: Any = None,
    user_id: uuid.UUID | None = None,
    request_id: str = "",
    approval_id: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Write one audit row.

    Echoes to the logger for dev visibility and persists to the DB.
    Pass `session` to enlist in an existing transaction; otherwise a
    new session is opened and committed for this row alone.
    """
    row = AuditRow(
        timestamp=datetime.now(timezone.utc),
        agent=agent,
        domain=domain,
        action_class=action_class,
        action_name=action_name,
        target_summary=target_summary,
        decision=decision,
        input_hash=hash_payload(input_payload) if input_payload is not None else "",
        output_hash=hash_payload(output_payload) if output_payload is not None else "",
        integration=integration,
        latency_ms=latency_ms,
        user_id=user_id,
        request_id=request_id,
        approval_id=approval_id,
        extra=extra or {},
    )
    logger.info("audit", extra={"audit": asdict(row)})
    await _persist(row, session=session)
