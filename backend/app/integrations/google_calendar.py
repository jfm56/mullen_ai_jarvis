"""Google Calendar integration.

Architecture:
  * OAuth client_id is non-secret and stored in .env (GOOGLE_OAUTH_CLIENT_ID).
  * OAuth client_secret is stored in keyring under 'google_oauth_client_secret'.
  * Per-account refresh tokens are stored in keyring under
    'google_refresh_token:{account_email}'.
  * An OAuthAccount row holds non-secret metadata (granted scopes, expiry).

Read-only by default. The `create_event` helper exists for use by the
agent layer ONLY after a corresponding Approval has been approved — it
does not check approvals itself; that's the agent's responsibility.

Tests that hit Google's real endpoints are marked `requires_google` (see
conftest.py). The unit-testable surface here is the URL builder and the
DB round-trip in `upsert_event`.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker
from app.db.models import CalendarEvent

PROVIDER = "google"
SCOPES_READ = ["https://www.googleapis.com/auth/calendar.readonly"]
SCOPES_WRITE = ["https://www.googleapis.com/auth/calendar.events"]

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - public OAuth endpoint
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"


class GoogleCalendarError(RuntimeError):
    pass


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: list[str]


def _client_id() -> str:
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not cid:
        raise GoogleCalendarError("GOOGLE_OAUTH_CLIENT_ID not configured")
    return cid


def _redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_OAUTH_REDIRECT", "http://127.0.0.1:8000/auth/google/callback"
    )


def authorize_url(*, state: str, scopes: list[str] | None = None) -> str:
    """Build the URL to send the user to for consent."""
    return _AUTH_URL + "?" + urlencode(
        {
            "client_id": _client_id(),
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": " ".join(scopes or SCOPES_READ),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "include_granted_scopes": "true",
        }
    )


# --- Event sync -------------------------------------------------------------


async def upsert_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    raw: dict[str, Any],
    calendar_id: str = "primary",
    domain: str = "personal",
) -> CalendarEvent:
    """Insert or update one event from Google's response shape.

    Idempotent on (source='google', external_id=raw['id']).
    """
    external_id = raw.get("id")
    if not external_id:
        raise GoogleCalendarError("event has no id")

    start_at, end_at, all_day = _parse_times(raw)

    result = await session.execute(
        select(CalendarEvent).where(
            CalendarEvent.source == PROVIDER,
            CalendarEvent.external_id == external_id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        event = CalendarEvent(
            user_id=user_id,
            source=PROVIDER,
            external_id=external_id,
            calendar_id=calendar_id,
            domain=domain,
            title=raw.get("summary", "(no title)"),
            description=raw.get("description", ""),
            location=raw.get("location", ""),
            start_at=start_at,
            end_at=end_at,
            all_day=all_day,
            raw=raw,
        )
        session.add(event)
    else:
        event.title = raw.get("summary", "(no title)")
        event.description = raw.get("description", "")
        event.location = raw.get("location", "")
        event.start_at = start_at
        event.end_at = end_at
        event.all_day = all_day
        event.synced_at = datetime.now(timezone.utc)
        event.raw = raw
    return event


def _parse_times(raw: dict[str, Any]) -> tuple[datetime, datetime, bool]:
    start = raw.get("start", {})
    end = raw.get("end", {})
    if "dateTime" in start:
        return (
            datetime.fromisoformat(start["dateTime"]),
            datetime.fromisoformat(end["dateTime"]),
            False,
        )
    if "date" in start:
        return (
            datetime.fromisoformat(start["date"]).replace(tzinfo=timezone.utc),
            datetime.fromisoformat(end["date"]).replace(tzinfo=timezone.utc),
            True,
        )
    raise GoogleCalendarError(f"event {raw.get('id')} has no start time")


async def list_local_events_for_day(
    user_id: uuid.UUID, day: datetime, *, domain: str = "personal"
) -> list[CalendarEvent]:
    """Read-only DB query — no Google call."""
    start_of_day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day.replace(hour=23, minute=59, second=59, microsecond=999999)
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.domain == domain,
                CalendarEvent.start_at >= start_of_day,
                CalendarEvent.start_at <= end_of_day,
            )
            .order_by(CalendarEvent.start_at)
        )
        return list(result.scalars().all())


# --- Sync ------------------------------------------------------------------


_CAL_API = "https://www.googleapis.com/calendar/v3"


async def sync_events(
    *,
    user_id: uuid.UUID,
    account_email: str,
    calendar_id: str = "primary",
    days_back: int = 1,
    days_forward: int = 30,
    domain: str = "personal",
) -> int:
    """Pull events from `time_min` to `time_max` and upsert each.

    Returns the number of events synced. Uses the stored OAuth refresh
    token (in keyring) to get a fresh access token.
    """
    import httpx
    from datetime import timedelta

    from app.integrations import google_oauth

    access_token = await google_oauth.access_token_for(account_email)

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_forward)).isoformat()

    synced = 0
    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {access_token}"}
    ) as client:
        page_token: str | None = None
        async with get_sessionmaker()() as session:
            while True:
                params = {
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 100,
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = await client.get(
                    f"{_CAL_API}/calendars/{calendar_id}/events", params=params
                )
                if resp.status_code >= 400:
                    raise GoogleCalendarError(
                        f"events.list failed: {resp.status_code} {resp.text[:200]}"
                    )
                payload = resp.json()
                for raw in payload.get("items") or []:
                    if raw.get("status") == "cancelled":
                        continue
                    try:
                        await upsert_event(
                            session, user_id=user_id, raw=raw,
                            calendar_id=calendar_id, domain=domain,
                        )
                        synced += 1
                    except GoogleCalendarError:
                        # Skip malformed events (no start time, etc.) — don't kill the sync.
                        continue
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
            await session.commit()
    return synced
