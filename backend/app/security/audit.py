"""Append-only audit log.

Every agent action, integration call, and approval decision is logged here.
Sensitive payloads are stored as hashes only — the audit log itself must
not be a leak vector.

Phase 1 will back this with a Postgres table whose role lacks UPDATE/DELETE
permission. For now this is the in-memory stub so other modules can import.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

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
    extra: dict[str, Any] = field(default_factory=dict)


def hash_payload(payload: Any) -> str:
    """Stable short hash for traceability without storing the payload."""
    encoded = repr(payload).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()[:16]


def record(row: AuditRow) -> None:
    logger.info("audit", extra={"audit": asdict(row)})


def emit(
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
    extra: dict[str, Any] | None = None,
) -> None:
    record(
        AuditRow(
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
            extra=extra or {},
        )
    )
