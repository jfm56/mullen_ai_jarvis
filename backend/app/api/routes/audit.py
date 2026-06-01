"""Audit log read API.

Read-only — the audit table itself has a DB trigger blocking UPDATE/DELETE.
This endpoint exists so the dashboard's "Recent activity" panel + the
AgentRoster can show what the system has been doing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.db.base import get_sessionmaker
from app.db.models import AuditLog, User
from app.security.auth import get_current_user

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryView(BaseModel):
    id: str
    timestamp: datetime
    agent: str
    domain: str
    action_class: str
    action_name: str
    target_summary: str
    decision: str
    latency_ms: int


class AgentStatusView(BaseModel):
    agent: str
    last_active: datetime | None
    actions_24h: int
    approvals_pending_24h: int
    has_activity: bool


@router.get("", response_model=list[AuditEntryView])
async def recent_audit(
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=500),
    agent: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=720),
) -> list[AuditEntryView]:
    """Most-recent-first audit entries scoped to the current user."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.timestamp >= cutoff,
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
    )
    if agent:
        stmt = stmt.where(AuditLog.agent == agent)
    # Audit log includes user_id for filtering. If a row has no user_id
    # (system-level events) include it; otherwise must match.
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [
        AuditEntryView(
            id=str(r.id),
            timestamp=r.timestamp,
            agent=r.agent,
            domain=r.domain,
            action_class=r.action_class,
            action_name=r.action_name,
            target_summary=r.target_summary,
            decision=r.decision,
            latency_ms=r.latency_ms,
        )
        for r in rows
        if r.user_id is None or r.user_id == user.id
    ]


# Known agent names — must match BaseAgent.name across the codebase.
_KNOWN_AGENTS = (
    "personal_assistant",
    "email_assistant",
    "project_manager",
    "marketing",
    "lead_generation",
    "business_development",
    "computer_control",
    "grant_writer",
    "proactive",
)


@router.get("/status", response_model=list[AgentStatusView])
async def agents_status(
    user: Annotated[User, Depends(get_current_user)],
) -> list[AgentStatusView]:
    """Per-agent activity rollup over the last 24 hours.

    Powers the dashboard's AgentRoster: shows whether each agent has been
    doing anything recently and (loosely) whether it's idle vs. active.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    async with get_sessionmaker()() as session:
        # One query, grouped by agent.
        result = await session.execute(
            select(
                AuditLog.agent,
                func.max(AuditLog.timestamp).label("last_active"),
                func.count(AuditLog.id).label("actions_24h"),
                func.sum(
                    case(
                        (AuditLog.decision == "require_approval", 1),
                        else_=0,
                    )
                ).label("approvals_24h"),
            )
            .where(AuditLog.timestamp >= cutoff)
            .group_by(AuditLog.agent)
        )
        rows = {r.agent: r for r in result.all()}

    out: list[AgentStatusView] = []
    for name in _KNOWN_AGENTS:
        r = rows.get(name)
        if r is None:
            out.append(
                AgentStatusView(
                    agent=name,
                    last_active=None,
                    actions_24h=0,
                    approvals_pending_24h=0,
                    has_activity=False,
                )
            )
        else:
            out.append(
                AgentStatusView(
                    agent=name,
                    last_active=r.last_active,
                    actions_24h=int(r.actions_24h or 0),
                    approvals_pending_24h=int(r.approvals_24h or 0),
                    has_activity=True,
                )
            )
    return out
