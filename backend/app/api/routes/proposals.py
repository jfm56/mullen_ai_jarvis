"""Proposals API.

The /draft endpoint generates a proposal AND queues an Approval for
external submission — the proposal text is persisted unconditionally,
but submitting it requires the user to settle the returned approval.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.business_development import BusinessDevelopmentAgent
from app.db.base import get_sessionmaker
from app.db.models import Opportunity, Project, Proposal, ProposalStatus, User
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/proposals", tags=["proposals"])


class ProposalView(BaseModel):
    id: str
    project_id: str | None
    opportunity_id: str | None
    title: str
    body_text: str
    status: str
    generated_by: str
    model: str
    submit_approval_id: str | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProposalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    body_text: str | None = Field(default=None, min_length=1, max_length=100_000)
    status: ProposalStatus | None = None


class DraftRequest(BaseModel):
    opportunity_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    user_instructions: str = Field(default="", max_length=2000)
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class DraftResponse(BaseModel):
    proposal: ProposalView
    approval_id: str | None
    approval_decision: str


def _to_view(p: Proposal) -> ProposalView:
    return ProposalView(
        id=str(p.id),
        project_id=str(p.project_id) if p.project_id else None,
        opportunity_id=str(p.opportunity_id) if p.opportunity_id else None,
        title=p.title,
        body_text=p.body_text,
        status=p.status.value,
        generated_by=p.generated_by,
        model=p.model,
        submit_approval_id=str(p.submit_approval_id) if p.submit_approval_id else None,
        submitted_at=p.submitted_at,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[ProposalView])
async def list_proposals(
    user: Annotated[User, Depends(get_current_user)],
    proposal_status: ProposalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ProposalView]:
    stmt = (
        select(Proposal)
        .where(Proposal.user_id == user.id)
        .order_by(Proposal.updated_at.desc())
        .limit(limit)
    )
    if proposal_status:
        stmt = stmt.where(Proposal.status == proposal_status)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(p) for p in result.scalars()]


@router.post("/draft", response_model=DraftResponse)
async def draft_proposal(
    body: DraftRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> DraftResponse:
    if body.opportunity_id is None and body.project_id is None:
        raise HTTPException(
            status_code=400, detail="provide opportunity_id or project_id"
        )

    async with get_sessionmaker()() as session:
        opp = None
        proj = None
        if body.opportunity_id:
            opp = await session.get(Opportunity, body.opportunity_id)
            if opp is None or opp.user_id != user.id:
                raise HTTPException(status_code=404, detail="opportunity not found")
        if body.project_id:
            proj = await session.get(Project, body.project_id)
            if proj is None or proj.user_id != user.id:
                raise HTTPException(status_code=404, detail="project not found")

    agent = BusinessDevelopmentAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain="business",
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()),
        input_text=body.user_instructions,
        metadata={},
    )
    proposal, outcome = await agent.draft_proposal(
        ctx,
        opportunity=opp,
        project=proj,
        user_instructions=body.user_instructions,
    )
    return DraftResponse(
        proposal=_to_view(proposal),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


@router.get("/{proposal_id}", response_model=ProposalView)
async def get_proposal(
    proposal_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> ProposalView:
    async with get_sessionmaker()() as session:
        p = await session.get(Proposal, proposal_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="proposal not found")
        return _to_view(p)


@router.patch("/{proposal_id}", response_model=ProposalView)
async def update_proposal(
    proposal_id: uuid.UUID,
    body: ProposalUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> ProposalView:
    async with get_sessionmaker()() as session:
        p = await session.get(Proposal, proposal_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="proposal not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(p, field_name, value)
        await session.commit()
        await session.refresh(p)
        return _to_view(p)


@router.delete("/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal(
    proposal_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        p = await session.get(Proposal, proposal_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="proposal not found")
        await session.delete(p)
        await session.commit()
