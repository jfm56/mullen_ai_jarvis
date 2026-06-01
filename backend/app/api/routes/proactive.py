"""Proactive recommendations API.

GET /proactive/recommendations — ranked list of "what needs Jim's attention now".

Read-only by design. The proactive agent surfaces; the gated agents act.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.agents.proactive import ProactiveAgent
from app.db.models import User
from app.security.auth import get_current_user

router = APIRouter(prefix="/proactive", tags=["proactive"])


class SuggestionView(BaseModel):
    title: str
    detail: str
    priority: str
    source_kind: str
    source_id: str
    suggested_route: str
    age_hours: int
    metadata: dict


class RecommendationsResponse(BaseModel):
    suggestions: list[SuggestionView]
    counts: dict[str, int]  # priority -> count


@router.get("/recommendations", response_model=RecommendationsResponse)
async def recommendations(
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
    domain: str | None = Query(default=None),
) -> RecommendationsResponse:
    agent = ProactiveAgent()
    suggestions = await agent.recommendations(
        user_id=user.id, limit=limit, domain=domain
    )

    views = [
        SuggestionView(
            title=s.title,
            detail=s.detail,
            priority=s.priority.value,
            source_kind=s.source_kind,
            source_id=s.source_id,
            suggested_route=s.suggested_route,
            age_hours=s.age_hours,
            metadata=s.metadata,
        )
        for s in suggestions
    ]
    counts: dict[str, int] = {}
    for v in views:
        counts[v.priority] = counts.get(v.priority, 0) + 1
    return RecommendationsResponse(suggestions=views, counts=counts)
