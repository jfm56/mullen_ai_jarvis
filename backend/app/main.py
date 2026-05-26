"""FastAPI entrypoint.

Run: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware.timing import TimingMiddleware
from app.config import get_settings
from app.security import redaction


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

    from app.api.routes import (
        agents,
        approvals,
        auth,
        backups,
        computer,
        emails,
        grants,
        health,
        leads,
        memory,
        opportunities,
        org_profiles,
        projects,
        proposals,
        reminders,
        social,
        tasks,
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(approvals.router)
    app.include_router(tasks.router)
    app.include_router(reminders.router)
    app.include_router(memory.router)
    app.include_router(emails.router)
    app.include_router(projects.router)
    app.include_router(opportunities.router)
    app.include_router(proposals.router)
    app.include_router(social.router)
    app.include_router(leads.router)
    app.include_router(computer.router)
    app.include_router(org_profiles.router)
    app.include_router(grants.router)
    app.include_router(backups.router)
    app.include_router(agents.router)
    return app


app = create_app()
