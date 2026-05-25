"""Opportunities API: grants, RFPs, partnerships, cold inbound, referrals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import (
    Opportunity,
    OpportunityKind,
    OpportunityStatus,
    User,
    Vertical,
)
from app.security.auth import get_current_user

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


class OpportunityView(BaseModel):
    id: str
    title: str
    agency_or_company: str
    kind: str
    vertical: str
    status: str
    url: str
    deadline: datetime | None
    value_estimate: float
    notes: str
    created_at: datetime
    updated_at: datetime


class OpportunityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    agency_or_company: str = Field(default="", max_length=255)
    kind: OpportunityKind = OpportunityKind.other
    vertical: Vertical = Vertical.other
    status: OpportunityStatus = OpportunityStatus.watching
    url: str = Field(default="", max_length=1024)
    deadline: datetime | None = None
    value_estimate: float = 0.0
    notes: str = Field(default="", max_length=10_000)


class OpportunityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    agency_or_company: str | None = Field(default=None, max_length=255)
    kind: OpportunityKind | None = None
    vertical: Vertical | None = None
    status: OpportunityStatus | None = None
    url: str | None = Field(default=None, max_length=1024)
    deadline: datetime | None = None
    value_estimate: float | None = None
    notes: str | None = Field(default=None, max_length=10_000)


def _to_view(o: Opportunity) -> OpportunityView:
    return OpportunityView(
        id=str(o.id),
        title=o.title,
        agency_or_company=o.agency_or_company,
        kind=o.kind.value,
        vertical=o.vertical.value,
        status=o.status.value,
        url=o.url,
        deadline=o.deadline,
        value_estimate=o.value_estimate,
        notes=o.notes,
        created_at=o.created_at,
        updated_at=o.updated_at,
    )


@router.get("", response_model=list[OpportunityView])
async def list_opportunities(
    user: Annotated[User, Depends(get_current_user)],
    opp_status: OpportunityStatus | None = Query(default=None, alias="status"),
    kind: OpportunityKind | None = Query(default=None),
    vertical: Vertical | None = Query(default=None),
    open_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[OpportunityView]:
    stmt = (
        select(Opportunity)
        .where(Opportunity.user_id == user.id)
        .order_by(Opportunity.deadline.asc().nullslast())
        .limit(limit)
    )
    if opp_status:
        stmt = stmt.where(Opportunity.status == opp_status)
    elif open_only:
        stmt = stmt.where(
            Opportunity.status.notin_(
                (OpportunityStatus.lost, OpportunityStatus.dropped, OpportunityStatus.won)
            )
        )
    if kind:
        stmt = stmt.where(Opportunity.kind == kind)
    if vertical:
        stmt = stmt.where(Opportunity.vertical == vertical)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(o) for o in result.scalars()]


@router.post("", response_model=OpportunityView, status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    body: OpportunityCreate, user: Annotated[User, Depends(get_current_user)]
) -> OpportunityView:
    opp = Opportunity(user_id=user.id, **body.model_dump())
    async with get_sessionmaker()() as session:
        session.add(opp)
        await session.commit()
        await session.refresh(opp)
    return _to_view(opp)


@router.get("/{opportunity_id}", response_model=OpportunityView)
async def get_opportunity(
    opportunity_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> OpportunityView:
    async with get_sessionmaker()() as session:
        o = await session.get(Opportunity, opportunity_id)
        if o is None or o.user_id != user.id:
            raise HTTPException(status_code=404, detail="opportunity not found")
        return _to_view(o)


@router.patch("/{opportunity_id}", response_model=OpportunityView)
async def update_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> OpportunityView:
    async with get_sessionmaker()() as session:
        o = await session.get(Opportunity, opportunity_id)
        if o is None or o.user_id != user.id:
            raise HTTPException(status_code=404, detail="opportunity not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(o, field_name, value)
        await session.commit()
        await session.refresh(o)
        return _to_view(o)


@router.delete("/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_opportunity(
    opportunity_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        o = await session.get(Opportunity, opportunity_id)
        if o is None or o.user_id != user.id:
            raise HTTPException(status_code=404, detail="opportunity not found")
        await session.delete(o)
        await session.commit()
