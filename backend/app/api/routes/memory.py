"""Memory API: list, search, edit, delete + topic disable management.

Route order matters: static paths like /memory/disabled-topics must be
declared before /memory/{memory_id}, otherwise FastAPI tries to parse
"disabled-topics" as a UUID and returns 422 instead of routing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.models import MemoryKind, User
from app.memory import controls, store
from app.security.auth import get_current_user

router = APIRouter(prefix="/memory", tags=["memory"])


# --- Views ------------------------------------------------------------------


class MemoryView(BaseModel):
    id: str
    domain: str
    kind: str
    text: str
    metadata: dict[str, Any]
    distance: float | None
    created_at: datetime


class MemoryUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] | None = None


class TopicDisableView(BaseModel):
    id: str
    domain: str
    pattern: str
    note: str
    created_at: datetime


class TopicDisableCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=64)
    pattern: str = Field(min_length=1, max_length=255)
    note: str = Field(default="", max_length=1000)


def _hit_to_view(hit: store.MemoryHit) -> MemoryView:
    return MemoryView(
        id=str(hit.id),
        domain=hit.domain,
        kind=hit.kind.value if hasattr(hit.kind, "value") else str(hit.kind),
        text=hit.text,
        metadata=hit.metadata,
        distance=hit.distance,
        created_at=hit.created_at,
    )


def _row_to_view(m: store.Memory) -> MemoryView:
    return MemoryView(
        id=str(m.id),
        domain=m.domain,
        kind=m.kind.value if hasattr(m.kind, "value") else str(m.kind),
        text=m.text,
        metadata=m.metadata_json or {},
        distance=None,
        created_at=m.created_at,
    )


def _td_to_view(r: object) -> TopicDisableView:
    return TopicDisableView(
        id=str(r.id),
        domain=r.domain,
        pattern=r.pattern,
        note=r.note,
        created_at=r.created_at,
    )


# --- Memory list/search -----------------------------------------------------


@router.get("", response_model=list[MemoryView])
async def list_or_search_memories(
    user: Annotated[User, Depends(get_current_user)],
    domain: str = Query(..., description="required: domain to scope to"),
    kind: MemoryKind | None = Query(default=None),
    q: str | None = Query(default=None, description="if set, semantic similarity search"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MemoryView]:
    if q:
        hits = await store.search(user_id=user.id, domain=domain, query=q, k=limit, kind=kind)
    else:
        hits = await store.list_recent(
            user_id=user.id, domain=domain, kind=kind, limit=limit
        )
    return [_hit_to_view(h) for h in hits]


# --- Topic disables (declared BEFORE /{memory_id} for path routing) ---------


@router.get("/disabled-topics", response_model=list[TopicDisableView])
async def list_disables(
    user: Annotated[User, Depends(get_current_user)],
) -> list[TopicDisableView]:
    return [_td_to_view(r) for r in await controls.list_topic_disables(user_id=user.id)]


@router.post(
    "/disabled-topics", response_model=TopicDisableView, status_code=status.HTTP_201_CREATED
)
async def add_disable(
    body: TopicDisableCreate, user: Annotated[User, Depends(get_current_user)]
) -> TopicDisableView:
    row = await controls.add_topic_disable(
        user_id=user.id, domain=body.domain, pattern=body.pattern, note=body.note
    )
    return _td_to_view(row)


@router.delete("/disabled-topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_disable(
    topic_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    ok = await controls.remove_topic_disable(user_id=user.id, topic_id=topic_id)
    if not ok:
        raise HTTPException(status_code=404, detail="topic disable not found")


# --- Memory by id (must come AFTER /disabled-topics) ------------------------


@router.get("/{memory_id}", response_model=MemoryView)
async def get_memory(
    memory_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> MemoryView:
    row = await store.get(memory_id, user_id=user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _row_to_view(row)


@router.patch("/{memory_id}", response_model=MemoryView)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> MemoryView:
    row = await store.update_text(
        memory_id, user_id=user.id, text=body.text, metadata=body.metadata
    )
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _row_to_view(row)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    ok = await store.soft_delete(memory_id, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")
