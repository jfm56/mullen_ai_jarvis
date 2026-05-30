"""Calendar API: sync from Google Calendar into the local DB.

Reads + writes against `calendar_events`. The Personal Assistant's "today"
view reads from this table; this endpoint is what populates it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import CalendarEvent, User
from app.integrations import google_calendar
from app.security.auth import get_current_user

router = APIRouter(prefix="/calendar", tags=["calendar"])


class EventView(BaseModel):
    id: str
    title: str
    description: str
    location: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    calendar_id: str
    domain: str


class SyncRequest(BaseModel):
    account_email: str = Field(min_length=3, max_length=255)
    calendar_id: str = Field(default="primary", max_length=255)
    days_back: int = Field(default=1, ge=0, le=90)
    days_forward: int = Field(default=30, ge=1, le=365)
    domain: str = Field(default="personal", max_length=64)


class SyncResponse(BaseModel):
    synced: int
    account_email: str
    calendar_id: str


def _to_view(e: CalendarEvent) -> EventView:
    return EventView(
        id=str(e.id),
        title=e.title,
        description=e.description,
        location=e.location,
        start_at=e.start_at,
        end_at=e.end_at,
        all_day=e.all_day,
        calendar_id=e.calendar_id,
        domain=e.domain,
    )


@router.get("/events", response_model=list[EventView])
async def list_events(
    user: Annotated[User, Depends(get_current_user)],
    days_back: int = Query(default=0, ge=0, le=30),
    days_forward: int = Query(default=7, ge=1, le=90),
    domain: str = Query(default="personal"),
) -> list[EventView]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_back)
    end = now + timedelta(days=days_forward)
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user.id,
                CalendarEvent.domain == domain,
                CalendarEvent.start_at >= start,
                CalendarEvent.start_at <= end,
            )
            .order_by(CalendarEvent.start_at)
        )
        return [_to_view(e) for e in result.scalars()]


@router.post("/sync", response_model=SyncResponse)
async def sync(
    body: SyncRequest, user: Annotated[User, Depends(get_current_user)]
) -> SyncResponse:
    """Pull events from Google Calendar into the local DB.

    Requires the OAuth flow to have been completed for `account_email`.
    Safe to re-run — idempotent on (source='google', external_id).
    """
    try:
        count = await google_calendar.sync_events(
            user_id=user.id,
            account_email=body.account_email,
            calendar_id=body.calendar_id,
            days_back=body.days_back,
            days_forward=body.days_forward,
            domain=body.domain,
        )
    except google_calendar.GoogleCalendarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SyncResponse(
        synced=count,
        account_email=body.account_email,
        calendar_id=body.calendar_id,
    )
