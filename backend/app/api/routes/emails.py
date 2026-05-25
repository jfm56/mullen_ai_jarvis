"""Email API: list, get, mark read/archived, draft, daily summary."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.email_assistant import EmailAssistantAgent
from app.agents.base import AgentContext
from app.db.base import get_sessionmaker
from app.db.models import Email, EmailCategory, EmailDraft, User
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/emails", tags=["emails"])


class EmailView(BaseModel):
    id: str
    from_addr: str
    to_addrs: str
    subject: str
    snippet: str
    received_at: datetime
    category: str
    urgency_score: float
    is_scam: bool
    scam_score: float
    scam_signals: list[str]
    read: bool
    archived: bool


class EmailDetailView(EmailView):
    body_text: str
    labels: list[str]
    cc_addrs: str


class EmailDraftView(BaseModel):
    id: str
    email_id: str | None
    to_addrs: str
    subject: str
    body_text: str
    created_at: datetime
    sent_at: datetime | None


class DraftRequest(BaseModel):
    user_instructions: str = Field(default="", max_length=2000)
    permission_level: PermissionLevel = PermissionLevel.draft_only


class DraftResponse(BaseModel):
    draft: EmailDraftView
    approval_id: str | None
    approval_decision: str  # 'require_approval' / 'allow' / 'deny'


class InboxSummaryView(BaseModel):
    total: int
    by_category: dict[str, int]
    waiting_on_user: int
    flagged_scam: int
    overdue_unread_days: int


def _to_view(e: Email) -> EmailView:
    return EmailView(
        id=str(e.id),
        from_addr=e.from_addr,
        to_addrs=e.to_addrs,
        subject=e.subject,
        snippet=e.snippet,
        received_at=e.received_at,
        category=e.category.value if hasattr(e.category, "value") else str(e.category),
        urgency_score=e.urgency_score,
        is_scam=e.is_scam,
        scam_score=e.scam_score,
        scam_signals=list(e.scam_signals or []),
        read=e.read,
        archived=e.archived,
    )


def _to_detail(e: Email) -> EmailDetailView:
    base = _to_view(e)
    return EmailDetailView(
        **base.model_dump(),
        body_text=e.body_text,
        labels=list(e.labels or []),
        cc_addrs=e.cc_addrs,
    )


def _draft_to_view(d: EmailDraft) -> EmailDraftView:
    return EmailDraftView(
        id=str(d.id),
        email_id=str(d.email_id) if d.email_id else None,
        to_addrs=d.to_addrs,
        subject=d.subject,
        body_text=d.body_text,
        created_at=d.created_at,
        sent_at=d.sent_at,
    )


@router.get("", response_model=list[EmailView])
async def list_emails(
    user: Annotated[User, Depends(get_current_user)],
    category: EmailCategory | None = Query(default=None),
    is_scam: bool | None = Query(default=None),
    unread_only: bool = Query(default=False),
    domain: str | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[EmailView]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(Email)
        .where(
            Email.user_id == user.id,
            Email.received_at >= cutoff,
            Email.archived.is_(False),
        )
        .order_by(Email.received_at.desc())
        .limit(limit)
    )
    if category is not None:
        stmt = stmt.where(Email.category == category)
    if is_scam is not None:
        stmt = stmt.where(Email.is_scam.is_(is_scam))
    if unread_only:
        stmt = stmt.where(Email.read.is_(False))
    if domain:
        stmt = stmt.where(Email.domain == domain)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(e) for e in result.scalars()]


@router.get("/summary", response_model=InboxSummaryView)
async def inbox_summary(
    user: Annotated[User, Depends(get_current_user)],
    domain: str = Query(default="personal"),
) -> InboxSummaryView:
    agent = EmailAssistantAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain=domain,
        permission_level=PermissionLevel.read_only,
        request_id=str(uuid.uuid4()),
        input_text="",
        metadata={},
    )
    s = await agent._summarize_inbox(ctx)
    return InboxSummaryView(
        total=s.total,
        by_category=s.by_category,
        waiting_on_user=s.waiting_on_user,
        flagged_scam=s.flagged_scam,
        overdue_unread_days=s.overdue_unread_days,
    )


@router.get("/{email_id}", response_model=EmailDetailView)
async def get_email(
    email_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> EmailDetailView:
    async with get_sessionmaker()() as session:
        e = await session.get(Email, email_id)
        if e is None or e.user_id != user.id:
            raise HTTPException(status_code=404, detail="email not found")
        return _to_detail(e)


@router.post("/{email_id}/read", response_model=EmailView)
async def mark_read(
    email_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> EmailView:
    async with get_sessionmaker()() as session:
        e = await session.get(Email, email_id)
        if e is None or e.user_id != user.id:
            raise HTTPException(status_code=404, detail="email not found")
        e.read = True
        await session.commit()
        await session.refresh(e)
        return _to_view(e)


@router.post("/{email_id}/archive", response_model=EmailView)
async def archive_email(
    email_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> EmailView:
    async with get_sessionmaker()() as session:
        e = await session.get(Email, email_id)
        if e is None or e.user_id != user.id:
            raise HTTPException(status_code=404, detail="email not found")
        e.archived = True
        await session.commit()
        await session.refresh(e)
        return _to_view(e)


@router.post("/{email_id}/categorize", response_model=EmailView)
async def recategorize_email(
    email_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> EmailView:
    """Re-run scam detection + categorizer for one email."""
    agent = EmailAssistantAgent()
    async with get_sessionmaker()() as session:
        e = await session.get(Email, email_id)
        if e is None or e.user_id != user.id:
            raise HTTPException(status_code=404, detail="email not found")
        await agent.enrich(e)
        await session.commit()
        await session.refresh(e)
        return _to_view(e)


@router.post("/{email_id}/draft", response_model=DraftResponse)
async def draft_reply(
    email_id: uuid.UUID,
    body: DraftRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> DraftResponse:
    """Generate a draft reply. The send is queued as a pending approval.

    The draft text is created regardless. The actual send requires the user
    to settle the returned approval via POST /approvals/{id}/decision.
    """
    async with get_sessionmaker()() as session:
        e = await session.get(Email, email_id)
        if e is None or e.user_id != user.id:
            raise HTTPException(status_code=404, detail="email not found")

    agent = EmailAssistantAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain=e.domain,
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()),
        input_text=body.user_instructions,
        metadata={},
    )
    draft, outcome = await agent.draft_reply(ctx, e, user_instructions=body.user_instructions)
    return DraftResponse(
        draft=_draft_to_view(draft),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )
