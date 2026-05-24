"""Tasks API: CRUD scoped to the current user."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Task, TaskPriority, TaskStatus, User
from app.security.auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskView(BaseModel):
    id: str
    title: str
    notes: str
    status: str
    priority: str
    domain: str
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    notes: str = Field(default="", max_length=10_000)
    priority: TaskPriority = TaskPriority.normal
    due_at: datetime | None = None
    domain: str = Field(default="personal", max_length=64)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=10_000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None


def _to_view(t: Task) -> TaskView:
    return TaskView(
        id=str(t.id),
        title=t.title,
        notes=t.notes,
        status=t.status.value if hasattr(t.status, "value") else str(t.status),
        priority=t.priority.value if hasattr(t.priority, "value") else str(t.priority),
        domain=t.domain,
        due_at=t.due_at,
        completed_at=t.completed_at,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("", response_model=list[TaskView])
async def list_tasks(
    user: Annotated[User, Depends(get_current_user)],
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    domain: str | None = Query(default=None),
) -> list[TaskView]:
    stmt = select(Task).where(Task.user_id == user.id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    if domain:
        stmt = stmt.where(Task.domain == domain)
    stmt = stmt.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(t) for t in result.scalars()]


@router.post("", response_model=TaskView, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate, user: Annotated[User, Depends(get_current_user)]
) -> TaskView:
    task = Task(
        user_id=user.id,
        title=body.title,
        notes=body.notes,
        priority=body.priority,
        due_at=body.due_at,
        domain=body.domain,
    )
    async with get_sessionmaker()() as session:
        session.add(task)
        await session.commit()
        await session.refresh(task)
    return _to_view(task)


@router.patch("/{task_id}", response_model=TaskView)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> TaskView:
    async with get_sessionmaker()() as session:
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user.id:
            raise HTTPException(status_code=404, detail="task not found")

        if body.title is not None:
            task.title = body.title
        if body.notes is not None:
            task.notes = body.notes
        if body.priority is not None:
            task.priority = body.priority
        if body.due_at is not None:
            task.due_at = body.due_at
        if body.status is not None:
            task.status = body.status
            if body.status is TaskStatus.done:
                task.completed_at = datetime.now(timezone.utc)
            else:
                task.completed_at = None

        await session.commit()
        await session.refresh(task)
        return _to_view(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user.id:
            raise HTTPException(status_code=404, detail="task not found")
        await session.delete(task)
        await session.commit()
