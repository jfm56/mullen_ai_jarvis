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

    from app.api.routes import (
        agents,
        approvals,
        auth,
        computer,
        emails,
        health,
        leads,
        memory,
        opportunities,
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
    app.include_router(agents.router)
    return app


app = create_app()
