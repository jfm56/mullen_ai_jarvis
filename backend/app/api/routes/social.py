"""Social posts API.

/draft generates a post AND queues a publish approval. The draft is
persisted unconditionally; publishing requires the user to settle the
approval. /suggest-topics is read-only utility.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.marketing import MarketingAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    SocialPlatform,
    SocialPost,
    SocialPostStatus,
    User,
    Vertical,
)
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/social-posts", tags=["social"])


class SocialPostView(BaseModel):
    id: str
    platform: str
    vertical: str
    title: str
    body_text: str
    tags: list[str]
    status: str
    scheduled_for: datetime | None
    published_at: datetime | None
    post_approval_id: str | None
    engagement: dict
    generated_by: str
    model: str
    created_at: datetime
    updated_at: datetime


class SocialPostUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    body_text: str | None = Field(default=None, min_length=1, max_length=20_000)
    status: SocialPostStatus | None = None
    scheduled_for: datetime | None = None
    engagement: dict | None = None


class DraftPostRequest(BaseModel):
    platform: SocialPlatform = SocialPlatform.linkedin
    vertical: Vertical
    topic: str = Field(min_length=1, max_length=500)
    user_instructions: str = Field(default="", max_length=2000)
    permission_level: PermissionLevel = PermissionLevel.draft_only


class DraftPostResponse(BaseModel):
    post: SocialPostView
    approval_id: str | None
    approval_decision: str


class SuggestTopicsRequest(BaseModel):
    vertical: Vertical
    count: int = Field(default=5, ge=1, le=20)


def _to_view(p: SocialPost) -> SocialPostView:
    return SocialPostView(
        id=str(p.id),
        platform=p.platform.value,
        vertical=p.vertical.value,
        title=p.title,
        body_text=p.body_text,
        tags=list(p.tags or []),
        status=p.status.value,
        scheduled_for=p.scheduled_for,
        published_at=p.published_at,
        post_approval_id=str(p.post_approval_id) if p.post_approval_id else None,
        engagement=dict(p.engagement or {}),
        generated_by=p.generated_by,
        model=p.model,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[SocialPostView])
async def list_posts(
    user: Annotated[User, Depends(get_current_user)],
    post_status: SocialPostStatus | None = Query(default=None, alias="status"),
    platform: SocialPlatform | None = Query(default=None),
    vertical: Vertical | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SocialPostView]:
    stmt = (
        select(SocialPost)
        .where(SocialPost.user_id == user.id)
        .order_by(SocialPost.updated_at.desc())
        .limit(limit)
    )
    if post_status:
        stmt = stmt.where(SocialPost.status == post_status)
    if platform:
        stmt = stmt.where(SocialPost.platform == platform)
    if vertical:
        stmt = stmt.where(SocialPost.vertical == vertical)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(p) for p in result.scalars()]


@router.post("/draft", response_model=DraftPostResponse)
async def draft_post(
    body: DraftPostRequest, user: Annotated[User, Depends(get_current_user)]
) -> DraftPostResponse:
    agent = MarketingAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain="business",
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()),
        input_text=body.user_instructions,
        metadata={},
    )
    post, outcome = await agent.draft_post(
        ctx,
        platform=body.platform,
        vertical=body.vertical,
        topic=body.topic,
        user_instructions=body.user_instructions,
    )
    return DraftPostResponse(
        post=_to_view(post),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


@router.post("/suggest-topics", response_model=list[str])
async def suggest_topics(
    body: SuggestTopicsRequest, _: Annotated[User, Depends(get_current_user)]
) -> list[str]:
    return MarketingAgent.suggest_topics(body.vertical, count=body.count)


@router.get("/{post_id}", response_model=SocialPostView)
async def get_post(
    post_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> SocialPostView:
    async with get_sessionmaker()() as session:
        p = await session.get(SocialPost, post_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="post not found")
        return _to_view(p)


@router.patch("/{post_id}", response_model=SocialPostView)
async def update_post(
    post_id: uuid.UUID,
    body: SocialPostUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> SocialPostView:
    async with get_sessionmaker()() as session:
        p = await session.get(SocialPost, post_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="post not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(p, field_name, value)
        await session.commit()
        await session.refresh(p)
        return _to_view(p)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        p = await session.get(SocialPost, post_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="post not found")
        await session.delete(p)
        await session.commit()
