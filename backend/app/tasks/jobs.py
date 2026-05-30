"""Background jobs.

Each function is enqueueable by RQ. They're plain functions (not async)
because RQ workers run sync code by default; we bridge to async via
asyncio.run inside each job.

Conventions:
  * `user_id` is the UUID of the User row whose data we're syncing.
  * `account_email` is the Google account the OAuth flow connected.
  * Each job is idempotent — re-running won't duplicate rows.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger("jarvis.jobs")


def sync_gmail(user_id: str, account_email: str, *, days: int = 7) -> int:
    """Pull recent Gmail messages for `account_email`. Returns count synced."""
    from app.integrations import gmail

    async def _run() -> int:
        return await gmail.sync_recent_emails(
            user_id=uuid.UUID(user_id),
            account_email=account_email,
            days=days,
        )

    count = asyncio.run(_run())
    logger.info("sync_gmail: synced=%d account=%s", count, account_email)
    return count


def sync_calendar(
    user_id: str,
    account_email: str,
    *,
    calendar_id: str = "primary",
    days_back: int = 1,
    days_forward: int = 30,
) -> int:
    """Pull events from a Google Calendar. Returns count synced."""
    from app.integrations import google_calendar

    async def _run() -> int:
        return await google_calendar.sync_events(
            user_id=uuid.UUID(user_id),
            account_email=account_email,
            calendar_id=calendar_id,
            days_back=days_back,
            days_forward=days_forward,
        )

    count = asyncio.run(_run())
    logger.info(
        "sync_calendar: synced=%d account=%s calendar=%s", count, account_email, calendar_id
    )
    return count


def fire_due_reminders(user_id: str) -> int:
    """Mark due reminders as fired. Returns count.

    Without a notification channel (desktop notify / push / SMS) this just
    flips `fired=True`. The UI's /reminders/due poll surfaces them either way.
    Wire a notification channel here later.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db.base import get_sessionmaker
    from app.db.models import Reminder

    async def _run() -> int:
        now = datetime.now(timezone.utc)
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Reminder).where(
                    Reminder.user_id == uuid.UUID(user_id),
                    Reminder.cancelled.is_(False),
                    Reminder.fired.is_(False),
                    Reminder.fire_at <= now,
                )
            )
            count = 0
            for r in result.scalars():
                r.fired = True
                r.fired_at = now
                count += 1
            await session.commit()
            return count

    fired = asyncio.run(_run())
    logger.info("fire_due_reminders: fired=%d", fired)
    return fired
