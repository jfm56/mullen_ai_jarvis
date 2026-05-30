"""rq-scheduler entrypoint — enqueues recurring sync jobs.

Run:  python -m app.tasks.scheduler

Reads which Google accounts to sync from the DB (`OAuthAccount` rows
with provider='google' and revoked_at IS NULL) and enqueues:

  * sync_gmail    every 15 minutes
  * sync_calendar every 15 minutes
  * fire_due_reminders every minute

The scheduler runs forever, sleeping ~60s between scheduler ticks.
The actual jobs run in the worker process (`app.tasks.worker`), so
keep both running.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime, timezone  # noqa: E402

from redis import Redis  # noqa: E402
from rq import Queue  # noqa: E402

from app.tasks.worker import QUEUE_NAME  # noqa: E402

logger = logging.getLogger("jarvis.scheduler")


def _connected_google_accounts() -> list[tuple[str, str]]:
    """Return [(user_id, account_email), ...] for active Google OAuth links."""
    from sqlalchemy import select

    from app.db.base import get_sessionmaker
    from app.db.models import OAuthAccount

    async def _run() -> list[tuple[str, str]]:
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(OAuthAccount).where(
                    OAuthAccount.provider == "google",
                    OAuthAccount.revoked_at.is_(None),
                )
            )
            return [(str(a.user_id), a.account_email) for a in result.scalars()]

    return asyncio.run(_run())


def tick(queue: Queue) -> None:
    """One scheduler iteration."""
    accounts = _connected_google_accounts()
    if not accounts:
        return
    for user_id, email in accounts:
        queue.enqueue("app.tasks.jobs.sync_gmail", user_id, email, job_timeout=300)
        queue.enqueue("app.tasks.jobs.sync_calendar", user_id, email, job_timeout=300)
        queue.enqueue("app.tasks.jobs.fire_due_reminders", user_id, job_timeout=60)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("JARVIS_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    conn = Redis.from_url(redis_url)
    conn.ping()
    queue = Queue(QUEUE_NAME, connection=conn)

    # Interval between scheduler ticks. Default 15 minutes (in seconds).
    # Lower to 60 for very chatty syncing in dev.
    interval = int(os.environ.get("JARVIS_SCHEDULER_INTERVAL_S", "900"))
    logger.info(
        "scheduler started (redis=%s, queue=%s, interval=%ds)",
        redis_url, QUEUE_NAME, interval,
    )

    while True:
        try:
            started = datetime.now(timezone.utc).isoformat()
            tick(queue)
            logger.info("scheduler tick complete at %s", started)
        except Exception:  # noqa: BLE001 - never let the scheduler die
            logger.exception("scheduler tick failed; continuing")
        time.sleep(interval)


if __name__ == "__main__":
    main()
