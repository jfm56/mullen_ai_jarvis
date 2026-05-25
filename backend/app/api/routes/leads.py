"""Leads + Outreach API.

POST /leads/{id}/score recomputes the heuristic score.
POST /leads/{id}/recommend-followup returns a suggested next-touch date.
POST /leads/{id}/draft-outreach generates + queues an outreach approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.lead_generation import LeadGenerationAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    Lead,
    LeadSource,
    LeadStatus,
    OutreachChannel,
    OutreachMessage,
    OutreachStatus,
    User,
    Vertical,
)
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/leads", tags=["leads"])


class LeadView(BaseModel):
    id: str
    name: str
    company: str
    role: str
    email: str
    phone: str
    vertical: str
    source: str
    status: str
    score: int
    notes: str
    last_contacted_at: datetime | None
    next_followup_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadCreate(BaseModel):
    name: str = Field(default="", max_length=255)
    company: str = Field(default="", max_length=255)
    role: str = Field(default="", max_length=255)
    email: str = Field(default="", max_length=512)
    phone: str = Field(default="", max_length=64)
    vertical: Vertical = Vertical.other
    source: LeadSource = LeadSource.manual
    status: LeadStatus = LeadStatus.researched
    notes: str = Field(default="", max_length=10_000)


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=512)
    phone: str | None = Field(default=None, max_length=64)
    vertical: Vertical | None = None
    source: LeadSource | None = None
    status: LeadStatus | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    last_contacted_at: datetime | None = None
    next_followup_at: datetime | None = None


class DraftOutreachRequest(BaseModel):
    channel: OutreachChannel = OutreachChannel.email
    user_instructions: str = Field(default="", max_length=2000)
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class OutreachView(BaseModel):
    id: str
    lead_id: str
    channel: str
    subject: str
    body_text: str
    status: str
    sent_approval_id: str | None
    sent_at: datetime | None
    created_at: datetime


class DraftOutreachResponse(BaseModel):
    outreach: OutreachView
    approval_id: str | None
    approval_decision: str


class FollowupRecommendation(BaseModel):
    next_followup_at: datetime | None
    reason: str


def _to_view(L: Lead) -> LeadView:
    return LeadView(
        id=str(L.id),
        name=L.name,
        company=L.company,
        role=L.role,
        email=L.email,
        phone=L.phone,
        vertical=L.vertical.value,
        source=L.source.value,
        status=L.status.value,
        score=L.score,
        notes=L.notes,
        last_contacted_at=L.last_contacted_at,
        next_followup_at=L.next_followup_at,
        created_at=L.created_at,
        updated_at=L.updated_at,
    )


def _outreach_to_view(m: OutreachMessage) -> OutreachView:
    return OutreachView(
        id=str(m.id),
        lead_id=str(m.lead_id),
        channel=m.channel.value,
        subject=m.subject,
        body_text=m.body_text,
        status=m.status.value,
        sent_approval_id=str(m.sent_approval_id) if m.sent_approval_id else None,
        sent_at=m.sent_at,
        created_at=m.created_at,
    )


@router.get("", response_model=list[LeadView])
async def list_leads(
    user: Annotated[User, Depends(get_current_user)],
    lead_status: LeadStatus | None = Query(default=None, alias="status"),
    vertical: Vertical | None = Query(default=None),
    open_only: bool = Query(default=True),
    min_score: int = Query(default=0, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[LeadView]:
    stmt = (
        select(Lead)
        .where(Lead.user_id == user.id, Lead.score >= min_score)
        .order_by(Lead.score.desc(), Lead.next_followup_at.asc().nullslast())
        .limit(limit)
    )
    if lead_status:
        stmt = stmt.where(Lead.status == lead_status)
    elif open_only:
        stmt = stmt.where(
            Lead.status.notin_((LeadStatus.lost, LeadStatus.won, LeadStatus.disqualified))
        )
    if vertical:
        stmt = stmt.where(Lead.vertical == vertical)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(L) for L in result.scalars()]


@router.post("", response_model=LeadView, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate, user: Annotated[User, Depends(get_current_user)]
) -> LeadView:
    lead = Lead(user_id=user.id, **body.model_dump())
    # Initial score on create.
    lead.score = LeadGenerationAgent.score_lead(lead)
    async with get_sessionmaker()() as session:
        session.add(lead)
        await session.commit()
        await session.refresh(lead)
    return _to_view(lead)


@router.get("/{lead_id}", response_model=LeadView)
async def get_lead(
    lead_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> LeadView:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
        return _to_view(L)


@router.patch("/{lead_id}", response_model=LeadView)
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> LeadView:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(L, field_name, value)
        # Rescore after edits — composition may have changed.
        L.score = LeadGenerationAgent.score_lead(L)
        await session.commit()
        await session.refresh(L)
        return _to_view(L)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
        await session.delete(L)
        await session.commit()


@router.post("/{lead_id}/score", response_model=LeadView)
async def rescore(
    lead_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> LeadView:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
        L.score = LeadGenerationAgent.score_lead(L)
        await session.commit()
        await session.refresh(L)
        return _to_view(L)


@router.post("/{lead_id}/recommend-followup", response_model=FollowupRecommendation)
async def recommend_followup(
    lead_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> FollowupRecommendation:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
    suggested = LeadGenerationAgent.recommend_followup(L)
    if suggested is None:
        reason = f"no follow-up — lead is in terminal status '{L.status.value}'"
    else:
        reason = f"cadence for status '{L.status.value}' from last_contact={L.last_contacted_at}"
    return FollowupRecommendation(next_followup_at=suggested, reason=reason)


@router.post("/{lead_id}/draft-outreach", response_model=DraftOutreachResponse)
async def draft_outreach(
    lead_id: uuid.UUID,
    body: DraftOutreachRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> DraftOutreachResponse:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
    agent = LeadGenerationAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain="business",
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()),
        input_text=body.user_instructions,
        metadata={},
    )
    msg, outcome = await agent.draft_outreach(
        ctx, L, channel=body.channel, user_instructions=body.user_instructions
    )
    return DraftOutreachResponse(
        outreach=_outreach_to_view(msg),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


@router.get("/{lead_id}/outreach", response_model=list[OutreachView])
async def list_lead_outreach(
    lead_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> list[OutreachView]:
    async with get_sessionmaker()() as session:
        L = await session.get(Lead, lead_id)
        if L is None or L.user_id != user.id:
            raise HTTPException(status_code=404, detail="lead not found")
        result = await session.execute(
            select(OutreachMessage)
            .where(OutreachMessage.lead_id == lead_id)
            .order_by(OutreachMessage.created_at.desc())
        )
        return [_outreach_to_view(m) for m in result.scalars()]
