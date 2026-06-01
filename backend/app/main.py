"""FastAPI entrypoint.

Run: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

# Windows compatibility: psycopg's async driver requires the SelectorEventLoop,
# but Python's Windows default since 3.8 is ProactorEventLoop. Set the policy
# at module import time so it runs before uvicorn (or any test client) spins
# up its loop. Must happen before the first asyncio call in the process.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI  # noqa: E402  (must come after the policy set)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.middleware.timing import TimingMiddleware  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.security import redaction  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Best-effort: warm up the local LLM so the first user request is fast.
    # Doesn't block startup if Ollama is down.
    if os.environ.get("JARVIS_SKIP_OLLAMA_WARMUP", "").lower() not in ("1", "true", "yes"):
        try:
            from app.integrations import ollama  # lazy

            await ollama.warmup(timeout=5.0)
        except Exception:  # noqa: BLE001
            logging.getLogger("jarvis").warning("ollama warmup skipped", exc_info=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    # Install redaction filter on the root logger before anything else logs.
    redaction.install()

    app = FastAPI(
        title="mullen_ai_jarvis",
        version="0.0.1",
        description="Secure local-first AI executive assistant.",
        lifespan=lifespan,
        debug=settings.env.value == "development",
    )

    slow_ms = int(os.environ.get("JARVIS_SLOW_REQUEST_MS", "1000"))
    app.add_middleware(TimingMiddleware, slow_threshold_ms=slow_ms)

    # CORS for the Next.js dev server. Default to localhost-only to match the
    # local-first architecture (docs/ARCHITECTURE.md).
    cors_origins = [
        o.strip() for o in os.environ.get(
            "JARVIS_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Process-Time"],
    )

    from app.api.routes import (
        agents,
        approvals,
        audit,
        auth,
        backups,
        calendar,
        computer,
        emails,
        grants,
        health,
        leads,
        memory,
        opportunities,
        org_profiles,
        proactive,
        projects,
        proposals,
        reminders,
        social,
        tasks,
        voice,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(approvals.router)
    app.include_router(tasks.router)
    app.include_router(reminders.router)
    app.include_router(memory.router)
    app.include_router(emails.router)
    app.include_router(calendar.router)
    app.include_router(projects.router)
    app.include_router(opportunities.router)
    app.include_router(proposals.router)
    app.include_router(social.router)
    app.include_router(leads.router)
    app.include_router(computer.router)
    app.include_router(org_profiles.router)
    app.include_router(grants.router)
    app.include_router(backups.router)
    app.include_router(voice.router)
    app.include_router(audit.router)
    app.include_router(proactive.router)
    app.include_router(agents.router)
    return app


app = create_app()
