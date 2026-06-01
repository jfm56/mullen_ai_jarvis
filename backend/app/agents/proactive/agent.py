"""Proactive Agent — the "AI Suggestions" engine.

From the user's brief: "Cooper staffing model hasn't been updated in 12 days"
and "South Branch proposal may qualify for new grant funding." Concrete,
specific, ranked. Not a chatbot summary — a sortable list of things that
should land on Jim's plate today.

Design rules:
  * NEVER suggests anything that requires `action.external_send` directly —
    that's the gated agents' job. Proactive surfaces; it doesn't act.
  * Every suggestion has a deterministic source row (lead/task/opportunity/
    project/approval) so the user can click through and verify.
  * Heuristic only (no LLM) so it's fast and predictable. Re-runnable on
    every dashboard load without a token cost.
  * Priority is rule-based with explicit weights — not vibes.

Signals (each contributes one or more suggestions):
  1. Overdue tasks            — Task.due_at < now, status pending/in_progress
  2. Overdue lead follow-ups  — Lead.next_followup_at < now, not terminal
  3. Imminent deadlines       — Opportunity.deadline within 7d, Grant within 14d
  4. Stale projects           — Project.updated_at older than 14d, status=active
  5. Forgotten approvals      — Approval.status=pending older than 24h
  6. Untriaged emails         — Email.category=waiting_on_me, unread, older than 24h
  7. High-score leads idle    — Lead.score >= 70 AND no recent outreach
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker
from app.db.models import (
    Approval,
    ApprovalStatus,
    Email,
    EmailCategory,
    GrantApplication,
    GrantApplicationStatus as GrantStatus,
    Lead,
    LeadStatus,
    Opportunity,
    OpportunityStatus,
    OutreachMessage,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)


class SuggestionPriority(str, enum.Enum):
    urgent = "urgent"   # overdue, high-stakes
    high = "high"       # within 48h or score >= 70
    medium = "medium"   # within a week
    low = "low"         # informational


# Stable order key so the UI sorts predictably.
_PRIORITY_RANK = {
    SuggestionPriority.urgent: 0,
    SuggestionPriority.high: 1,
    SuggestionPriority.medium: 2,
    SuggestionPriority.low: 3,
}


@dataclass
class Suggestion:
    """One actionable suggestion for the dashboard.

    `source_kind` + `source_id` let the UI link back to the row this came from
    (e.g., source_kind='task' + source_id=<uuid> → /tasks?focus=<uuid>).
    """

    title: str
    detail: str
    priority: SuggestionPriority
    source_kind: str
    source_id: str
    suggested_route: str          # frontend route the UI can link to
    age_hours: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Context:
    user_id: uuid.UUID
    now: datetime


class ProactiveAgent:
    """Heuristic suggestion engine. No LLM, no network, no token cost."""

    name = "proactive"

    async def recommendations(
        self,
        *,
        user_id: uuid.UUID,
        limit: int = 20,
        domain: str | None = None,  # optional filter; None = all domains
    ) -> list[Suggestion]:
        """Collect signals from every source and return them ranked.

        Heaviest signals first (urgent before high). Ties broken by
        suggestion age (older items rank above newer ones at the same
        priority — "this has been sitting longer" wins).
        """
        ctx = _Context(user_id=user_id, now=datetime.now(timezone.utc))
        async with get_sessionmaker()() as session:
            all_suggestions: list[Suggestion] = []
            all_suggestions.extend(await self._overdue_tasks(session, ctx))
            all_suggestions.extend(await self._overdue_lead_followups(session, ctx))
            all_suggestions.extend(await self._opportunity_deadlines(session, ctx))
            all_suggestions.extend(await self._grant_deadlines(session, ctx))
            all_suggestions.extend(await self._stale_projects(session, ctx))
            all_suggestions.extend(await self._forgotten_approvals(session, ctx))
            all_suggestions.extend(await self._waiting_on_me_emails(session, ctx))
            all_suggestions.extend(await self._idle_high_score_leads(session, ctx))

        all_suggestions.sort(
            key=lambda s: (_PRIORITY_RANK[s.priority], -s.age_hours)
        )
        return all_suggestions[:limit]

    # ---- signal generators ------------------------------------------------

    async def _overdue_tasks(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        result = await session.execute(
            select(Task).where(
                Task.user_id == ctx.user_id,
                Task.status.in_((TaskStatus.pending, TaskStatus.in_progress)),
                Task.due_at.is_not(None),
                Task.due_at < ctx.now,
            )
        )
        out: list[Suggestion] = []
        for t in result.scalars():
            hours = int((ctx.now - t.due_at).total_seconds() // 3600)
            priority = (
                SuggestionPriority.urgent
                if hours >= 24
                else SuggestionPriority.high
            )
            out.append(
                Suggestion(
                    title=f"Overdue task: {t.title}",
                    detail=(
                        f"Due {t.due_at.strftime('%b %d')} — "
                        f"{hours // 24}d {hours % 24}h overdue"
                        if hours >= 24
                        else f"Due {t.due_at.strftime('%b %d %H:%M')} — {hours}h overdue"
                    ),
                    priority=priority,
                    source_kind="task",
                    source_id=str(t.id),
                    suggested_route=f"/tasks?focus={t.id}",
                    age_hours=hours,
                )
            )
        return out

    async def _overdue_lead_followups(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        result = await session.execute(
            select(Lead).where(
                Lead.user_id == ctx.user_id,
                Lead.status.notin_(
                    (LeadStatus.won, LeadStatus.lost, LeadStatus.disqualified)
                ),
                Lead.next_followup_at.is_not(None),
                Lead.next_followup_at < ctx.now,
            )
        )
        out: list[Suggestion] = []
        for L in result.scalars():
            hours = int((ctx.now - L.next_followup_at).total_seconds() // 3600)
            name = L.name or L.email or "(unnamed lead)"
            org = f" at {L.company}" if L.company else ""
            priority = (
                SuggestionPriority.urgent
                if L.score >= 70 or hours >= 72
                else SuggestionPriority.high
            )
            out.append(
                Suggestion(
                    title=f"Follow up with {name}{org}",
                    detail=(
                        f"Cadence-scheduled {hours // 24}d {hours % 24}h ago. "
                        f"Stage: {L.status.value}, score {L.score}."
                    ),
                    priority=priority,
                    source_kind="lead",
                    source_id=str(L.id),
                    suggested_route=f"/leads?focus={L.id}",
                    age_hours=hours,
                    metadata={"score": L.score, "vertical": L.vertical.value},
                )
            )
        return out

    async def _opportunity_deadlines(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        soon = ctx.now + timedelta(days=14)
        result = await session.execute(
            select(Opportunity).where(
                Opportunity.user_id == ctx.user_id,
                Opportunity.status.notin_(
                    (
                        OpportunityStatus.won,
                        OpportunityStatus.lost,
                        OpportunityStatus.dropped,
                        OpportunityStatus.submitted,
                    )
                ),
                Opportunity.deadline.is_not(None),
                Opportunity.deadline <= soon,
                Opportunity.deadline >= ctx.now,
            )
        )
        out: list[Suggestion] = []
        for o in result.scalars():
            hours_until = int((o.deadline - ctx.now).total_seconds() // 3600)
            days_until = hours_until // 24
            if days_until <= 2:
                priority = SuggestionPriority.urgent
            elif days_until <= 7:
                priority = SuggestionPriority.high
            else:
                priority = SuggestionPriority.medium
            agency = f" [{o.agency_or_company}]" if o.agency_or_company else ""
            value = f" — est ${o.value_estimate:,.0f}" if o.value_estimate else ""
            out.append(
                Suggestion(
                    title=f"Deadline in {days_until}d: {o.title}{agency}",
                    detail=(
                        f"{o.kind.value} / {o.vertical.value}, status {o.status.value}{value}"
                    ),
                    priority=priority,
                    source_kind="opportunity",
                    source_id=str(o.id),
                    suggested_route=f"/opportunities?focus={o.id}",
                    age_hours=-hours_until,  # negative → "until" not "since"
                )
            )
        return out

    async def _grant_deadlines(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        soon = ctx.now + timedelta(days=21)
        result = await session.execute(
            select(GrantApplication).where(
                GrantApplication.user_id == ctx.user_id,
                GrantApplication.status.notin_(
                    (
                        GrantStatus.submitted,
                        GrantStatus.awarded,
                        GrantStatus.declined,
                        GrantStatus.withdrawn,
                    )
                ),
                GrantApplication.deadline.is_not(None),
                GrantApplication.deadline <= soon,
                GrantApplication.deadline >= ctx.now,
            )
        )
        out: list[Suggestion] = []
        for g in result.scalars():
            hours_until = int((g.deadline - ctx.now).total_seconds() // 3600)
            days_until = hours_until // 24
            if days_until <= 3:
                priority = SuggestionPriority.urgent
            elif days_until <= 10:
                priority = SuggestionPriority.high
            else:
                priority = SuggestionPriority.medium
            funder = f" [{g.funder_name}]" if g.funder_name else ""
            value = (
                f" — requesting ${g.requested_amount:,.0f}"
                if g.requested_amount
                else ""
            )
            out.append(
                Suggestion(
                    title=f"Grant due in {days_until}d: {g.title}{funder}",
                    detail=(
                        f"Status: {g.status.value} / eligibility: "
                        f"{g.eligibility_verdict.value}{value}"
                    ),
                    priority=priority,
                    source_kind="grant",
                    source_id=str(g.id),
                    suggested_route=f"/grants?focus={g.id}",
                    age_hours=-hours_until,
                )
            )
        return out

    async def _stale_projects(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        cutoff = ctx.now - timedelta(days=14)
        result = await session.execute(
            select(Project).where(
                Project.user_id == ctx.user_id,
                Project.status == ProjectStatus.active,
                Project.updated_at < cutoff,
            )
        )
        out: list[Suggestion] = []
        for p in result.scalars():
            hours = int((ctx.now - p.updated_at).total_seconds() // 3600)
            days = hours // 24
            client = f" ({p.client})" if p.client else ""
            out.append(
                Suggestion(
                    title=f"{p.name}{client} hasn't been updated in {days} days",
                    detail=(
                        f"Active {p.vertical.value} project, no notes or "
                        f"status changes since {p.updated_at.strftime('%b %d')}."
                    ),
                    priority=(
                        SuggestionPriority.high if days >= 30 else SuggestionPriority.medium
                    ),
                    source_kind="project",
                    source_id=str(p.id),
                    suggested_route=f"/projects?focus={p.id}",
                    age_hours=hours,
                )
            )
        return out

    async def _forgotten_approvals(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        cutoff = ctx.now - timedelta(hours=24)
        result = await session.execute(
            select(Approval).where(
                Approval.status == ApprovalStatus.pending,
                Approval.created_at < cutoff,
            )
        )
        out: list[Suggestion] = []
        for a in result.scalars():
            hours = int((ctx.now - a.created_at).total_seconds() // 3600)
            priority = (
                SuggestionPriority.urgent if hours >= 72 else SuggestionPriority.high
            )
            out.append(
                Suggestion(
                    title=f"Approval pending {hours}h: {a.action_name}",
                    detail=f"{a.agent} → {a.target_summary[:120]}",
                    priority=priority,
                    source_kind="approval",
                    source_id=str(a.id),
                    suggested_route=f"/approvals?focus={a.id}",
                    age_hours=hours,
                )
            )
        return out

    async def _waiting_on_me_emails(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        cutoff = ctx.now - timedelta(hours=24)
        result = await session.execute(
            select(Email).where(
                Email.user_id == ctx.user_id,
                Email.category == EmailCategory.waiting_on_me,
                Email.read.is_(False),
                Email.archived.is_(False),
                Email.received_at < cutoff,
            )
        )
        out: list[Suggestion] = []
        for e in result.scalars():
            hours = int((ctx.now - e.received_at).total_seconds() // 3600)
            sender = e.from_addr.split("<")[0].strip() or e.from_addr
            priority = (
                SuggestionPriority.urgent if hours >= 72 else SuggestionPriority.high
            )
            out.append(
                Suggestion(
                    title=f"Reply to {sender}",
                    detail=f"Subject: {e.subject[:100]} — waiting {hours}h",
                    priority=priority,
                    source_kind="email",
                    source_id=str(e.id),
                    suggested_route=f"/emails?focus={e.id}",
                    age_hours=hours,
                )
            )
        return out

    async def _idle_high_score_leads(
        self, session: AsyncSession, ctx: _Context
    ) -> list[Suggestion]:
        """Leads with score >= 70 that haven't been contacted in 7+ days."""
        cutoff = ctx.now - timedelta(days=7)
        result = await session.execute(
            select(Lead).where(
                Lead.user_id == ctx.user_id,
                Lead.score >= 70,
                Lead.status.in_(
                    (LeadStatus.researched, LeadStatus.contacted, LeadStatus.meeting)
                ),
            )
        )
        out: list[Suggestion] = []
        for L in result.scalars():
            # Skip if we have a recent outreach message
            recent_outreach = await session.execute(
                select(OutreachMessage)
                .where(
                    OutreachMessage.lead_id == L.id,
                    OutreachMessage.created_at >= cutoff,
                )
                .limit(1)
            )
            if recent_outreach.scalar_one_or_none() is not None:
                continue
            # Skip if we have a follow-up scheduled in the future (cadence is handling it)
            if L.next_followup_at and L.next_followup_at > ctx.now:
                continue
            org = f" at {L.company}" if L.company else ""
            out.append(
                Suggestion(
                    title=f"High-score lead idle: {L.name or L.email}{org}",
                    detail=(
                        f"Score {L.score}, {L.vertical.value}, status {L.status.value}. "
                        "No outreach in 7+ days and no follow-up scheduled."
                    ),
                    priority=SuggestionPriority.medium,
                    source_kind="lead",
                    source_id=str(L.id),
                    suggested_route=f"/leads?focus={L.id}",
                    age_hours=0,
                    metadata={"score": L.score},
                )
            )
        return out
