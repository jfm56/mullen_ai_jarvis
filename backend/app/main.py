"""FastAPI entrypoint.

Run: uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="mullen_ai_jarvis",
        version="0.0.1",
        description="Secure local-first AI executive assistant.",
        lifespan=lifespan,
        debug=settings.env.value == "development",
    )

    from app.api.routes import agents, approvals, auth, health, reminders, tasks

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(approvals.router)
    app.include_router(tasks.router)
    app.include_router(reminders.router)
    app.include_router(agents.router)
    return app


app = create_app()
