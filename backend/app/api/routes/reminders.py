"""Reminders API: scheduled-time prompts surfaced to the user.

Phase 2 stores reminders; the RQ worker that actually fires them at
their scheduled time lands once Redis is provisioned. Until then,
`GET /reminders/due` returns what would have fired and the UI can
surface them on poll.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import Reminder, User
from app.security.auth import get_current_user

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderView(BaseModel):
    id: str
    text: str
    fire_at: datetime
    fired: bool
    fired_at: datetime | None
    cancelled: bool
    task_id: str | None
    domain: str
    created_at: datetime


class ReminderCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    fire_at: datetime
    task_id: uuid.UUID | None = None
    domain: str = Field(default="personal", max_length=64)


def _to_view(r: Reminder) -> ReminderView:
    return ReminderView(
        id=str(r.id),
        text=r.text,
        fire_at=r.fire_at,
        fired=r.fired,
        fired_at=r.fired_at,
        cancelled=r.cancelled,
        task_id=str(r.task_id) if r.task_id else None,
        domain=r.domain,
        created_at=r.created_at,
    )


@router.get("", response_model=list[ReminderView])
async def list_reminders(
    user: Annotated[User, Depends(get_current_user)],
) -> list[ReminderView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Reminder)
            .where(Reminder.user_id == user.id, Reminder.cancelled.is_(False))
            .order_by(Reminder.fire_at.asc())
        )
        return [_to_view(r) for r in result.scalars()]


@router.get("/due", response_model=list[ReminderView])
async def list_due_reminders(
    user: Annotated[User, Depends(get_current_user)],
) -> list[ReminderView]:
    now = datetime.now(timezone.utc)
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user.id,
                Reminder.fired.is_(False),
                Reminder.cancelled.is_(False),
                Reminder.fire_at <= now,
            )
            .order_by(Reminder.fire_at.asc())
        )
        return [_to_view(r) for r in result.scalars()]


@router.post("", response_model=ReminderView, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    body: ReminderCreate, user: Annotated[User, Depends(get_current_user)]
) -> ReminderView:
    reminder = Reminder(
        user_id=user.id,
        text=body.text,
        fire_at=body.fire_at,
        task_id=body.task_id,
        domain=body.domain,
    )
    async with get_sessionmaker()() as session:
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)
    return _to_view(reminder)


@router.post("/{reminder_id}/cancel", response_model=ReminderView)
async def cancel_reminder(
    reminder_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> ReminderView:
    async with get_sessionmaker()() as session:
        reminder = await session.get(Reminder, reminder_id)
        if reminder is None or reminder.user_id != user.id:
            raise HTTPException(status_code=404, detail="reminder not found")
        reminder.cancelled = True
        await session.commit()
        await session.refresh(reminder)
    return _to_view(reminder)


@router.post("/{reminder_id}/ack", response_model=ReminderView)
async def acknowledge_reminder(
    reminder_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> ReminderView:
    """Mark a reminder as fired (acknowledged by the user)."""
    async with get_sessionmaker()() as session:
        reminder = await session.get(Reminder, reminder_id)
        if reminder is None or reminder.user_id != user.id:
            raise HTTPException(status_code=404, detail="reminder not found")
        reminder.fired = True
        reminder.fired_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(reminder)
    return _to_view(reminder)
