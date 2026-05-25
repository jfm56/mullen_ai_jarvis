"""Memory write-back from approval decisions.

The hook strategy:
  * APPROVED action  → procedural memory ("when X, the user wants Y")
  * REJECTED action  → semantic preference memory ("don't do X in context Y")
  * REJECTED + note  → also store the note verbatim as a semantic memory,
                       since rejection notes are direct user instructions.

These are best-effort: a failure to write a memory must never block an
approval from settling, so all calls here are wrapped and logged.
"""

from __future__ import annotations

import logging

from app.db.models import Approval, ApprovalStatus, MemoryKind
from app.memory import store

logger = logging.getLogger("jarvis.memory.learning")


def _summary(approval: Approval, *, prefix: str) -> str:
    return (
        f"{prefix}: agent={approval.agent} action={approval.action_name} "
        f"target={approval.target_summary}"
    )


async def write_from_approval(approval: Approval) -> None:
    """Best-effort: derive memories from a settled approval. Never raises."""
    try:
        if approval.status is ApprovalStatus.approved:
            await store.write(
                user_id=approval.decided_by,
                domain=approval.domain,
                kind=MemoryKind.procedural,
                text=_summary(approval, prefix="approved"),
                metadata={
                    "action_class": approval.action_class,
                    "request_id": approval.request_id,
                },
                source_approval_id=approval.id,
            )
        elif approval.status is ApprovalStatus.rejected:
            await store.write(
                user_id=approval.decided_by,
                domain=approval.domain,
                kind=MemoryKind.semantic,
                text=_summary(approval, prefix="rejected"),
                metadata={
                    "action_class": approval.action_class,
                    "request_id": approval.request_id,
                },
                source_approval_id=approval.id,
            )
            if approval.decision_note.strip():
                await store.write(
                    user_id=approval.decided_by,
                    domain=approval.domain,
                    kind=MemoryKind.semantic,
                    text=f"user preference: {approval.decision_note.strip()}",
                    metadata={
                        "from_rejection": True,
                        "request_id": approval.request_id,
                    },
                    source_approval_id=approval.id,
                )
    except store.TopicDisabledError as exc:
        logger.info("approval-derived memory skipped by topic disable: %s", exc)
    except Exception:
        # Best-effort. Don't propagate.
        logger.exception("failed to write approval-derived memory")
