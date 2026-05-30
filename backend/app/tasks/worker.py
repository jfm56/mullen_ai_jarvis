"""RQ worker entrypoint.

Run:  python -m app.tasks.worker

Connects to Redis (default redis://localhost:6379), registers the
jarvis queue, and processes jobs forever. Use the same Python venv
that runs the API so jobs see the same models and integrations.

Scheduling: rq-scheduler enqueues `sync_gmail` and `sync_calendar`
every 15 minutes. Run the scheduler separately:
    python -m app.tasks.scheduler

This module deliberately stays small. The real work lives in
`app.tasks.jobs` (importable both by the worker and by ad-hoc test
runs).
"""

from __future__ import annotations

import logging
import os
import sys

# Windows compatibility: psycopg async driver needs SelectorEventLoop.
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from redis import Redis  # noqa: E402
from rq import Queue, Worker  # noqa: E402

QUEUE_NAME = "jarvis"


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("JARVIS_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    conn = Redis.from_url(redis_url)

    # Sanity ping so we fail fast if Redis isn't up.
    conn.ping()

    queue = Queue(QUEUE_NAME, connection=conn)
    worker = Worker([queue], connection=conn)
    logging.getLogger("jarvis.worker").info(
        "RQ worker listening on %s (queue=%s)", redis_url, QUEUE_NAME
    )
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
