"""Approvals queue.

When the permission engine returns `require_approval`, the agent calls
`create_pending(...)` to stash the proposed action. The user reviews it
via `GET /approvals` and settles it via `POST /approvals/{id}/decision`.

The audit log gets a row for the original proposal AND for the eventual
decision; both rows share the same `approval_id` so the lifecycle is
queryable end-to-end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker
from app.db.models import Approval, ApprovalStatus
from app.security import audit


_DEFAULT_TTL = timedelta(hours=24)


async def create_pending(
    *,
    agent: str,
    domain: str,
    action_class: str,
    action_name: str,
    target_summary: str,
    preview: str = "",
    payload: dict[str, Any] | None = None,
    request_id: str = "",
    ttl: timedelta | None = None,
    session: AsyncSession | None = None,
) -> Approval:
    """Insert a pending approval and audit it.

    Returns the persisted Approval. The caller can hand its id back to
    the UI / voice layer so the user knows what to look for.
    """
    expires_at = datetime.now(timezone.utc) + (ttl or _DEFAULT_TTL)
    approval = Approval(
        agent=agent,
        domain=domain,
        action_class=action_class,
        action_name=action_name,
        target_summary=target_summary,
        preview=preview,
        payload=payload or {},
        status=ApprovalStatus.pending,
        request_id=request_id,
        expires_at=expires_at,
    )

    async def _within(s: AsyncSession) -> Approval:
        s.add(approval)
        await s.flush()  # populates approval.id
        await audit.emit(
            agent=agent,
            domain=domain,
            action_class=action_class,
            action_name=action_name,
            target_summary=target_summary,
            decision="approval_queued",
            request_id=request_id,
            approval_id=approval.id,
            session=s,
        )
        return approval

    if session is not None:
        return await _within(session)

    async with get_sessionmaker()() as owned:
        result = await _within(owned)
        await owned.commit()
        await owned.refresh(result)
        return result


async def list_pending(*, agent: str | None = None, domain: str | None = None) -> list[Approval]:
    stmt = select(Approval).where(Approval.status == ApprovalStatus.pending)
    if agent:
        stmt = stmt.where(Approval.agent == agent)
    if domain:
        stmt = stmt.where(Approval.domain == domain)
    stmt = stmt.order_by(Approval.created_at.desc())
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get(approval_id: uuid.UUID) -> Approval | None:
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Approval).where(Approval.id == approval_id))
        return result.scalar_one_or_none()


class ApprovalError(RuntimeError):
    pass


async def decide(
    approval_id: uuid.UUID,
    *,
    approve: bool,
    decided_by: uuid.UUID,
    note: str = "",
) -> Approval:
    """Approve or reject a pending approval. Audits the decision.

    Raises ApprovalError if the approval is missing or already settled.
    The actual execution of an approved action is the caller's job — this
    function only records consent. The executor is responsible for the
    follow-up `executed`/`failed` status update via `mark_outcome`.
    """
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Approval).where(Approval.id == approval_id))
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalError(f"approval {approval_id} not found")
        if approval.status is not ApprovalStatus.pending:
            raise ApprovalError(f"approval {approval_id} already {approval.status.value}")
        if approval.expires_at and approval.expires_at < datetime.now(timezone.utc):
            approval.status = ApprovalStatus.expired
            await audit.emit(
                agent=approval.agent,
                domain=approval.domain,
                action_class=approval.action_class,
                action_name=approval.action_name,
                target_summary=approval.target_summary,
                decision="approval_expired",
                user_id=decided_by,
                approval_id=approval.id,
                session=session,
            )
            await session.commit()
            raise ApprovalError(f"approval {approval_id} expired")

        approval.status = ApprovalStatus.approved if approve else ApprovalStatus.rejected
        approval.decided_at = datetime.now(timezone.utc)
        approval.decided_by = decided_by
        approval.decision_note = note

        await audit.emit(
            agent=approval.agent,
            domain=approval.domain,
            action_class=approval.action_class,
            action_name=approval.action_name,
            target_summary=approval.target_summary,
            decision=f"approval_{approval.status.value}",
            user_id=decided_by,
            request_id=approval.request_id,
            approval_id=approval.id,
            extra={"note": note} if note else None,
            session=session,
        )
        await session.commit()
        await session.refresh(approval)

    # Fire the learning hook OUTSIDE the transaction so an embedding hiccup
    # cannot roll back the user's settled decision.
    # Lazy import to avoid an app.memory ↔ app.security cycle at module load.
    from app.memory import learning as _learning  # noqa: PLC0415

    await _learning.write_from_approval(approval)
    return approval


async def mark_outcome(
    approval_id: uuid.UUID, *, executed: bool, note: str = ""
) -> Approval:
    """Update an approved row's status to executed or failed after the executor runs."""
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Approval).where(Approval.id == approval_id))
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalError(f"approval {approval_id} not found")
        if approval.status is not ApprovalStatus.approved:
            raise ApprovalError(
                f"cannot mark outcome on approval in status {approval.status.value}"
            )
        approval.status = ApprovalStatus.executed if executed else ApprovalStatus.failed
        if note:
            approval.decision_note = (approval.decision_note + "\n" + note).strip()
        await audit.emit(
            agent=approval.agent,
            domain=approval.domain,
            action_class=approval.action_class,
            action_name=approval.action_name,
            target_summary=approval.target_summary,
            decision=f"action_{approval.status.value}",
            approval_id=approval.id,
            extra={"note": note} if note else None,
            session=session,
        )
        await session.commit()
        await session.refresh(approval)
        return approval
