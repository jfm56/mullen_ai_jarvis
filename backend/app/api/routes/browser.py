"""Browser Control API.

Admin-only allow-list CRUD + gated session and action endpoints.

Caveat: live Playwright sessions live in-process. If the server restarts,
the session DB row remains but the Playwright handle is gone — calls
return 410 Gone.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.computer_control import ComputerControlAgent
from app.agents.computer_control import browser_actions as ba
from app.db.base import get_sessionmaker
from app.db.models import (
    BrowserAction,
    BrowserAllowedDomain,
    BrowserSession,
    BrowserSessionStatus,
    User,
)
from app.integrations.computer import browser as pw
from app.security.auth import get_current_user, require_admin
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/computer/browser", tags=["computer-browser"])


# ---- Views ----------------------------------------------------------------


class AllowedDomainView(BaseModel):
    id: str
    pattern: str
    description: str
    allow_form_submit: bool
    created_at: datetime


class AllowedDomainCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    allow_form_submit: bool = False


class SessionView(BaseModel):
    id: str
    label: str
    status: str
    current_url: str
    idle_timeout_seconds: int
    started_at: datetime
    last_active_at: datetime
    closed_at: datetime | None
    is_live: bool


class StartSessionRequest(BaseModel):
    label: str = Field(default="", max_length=128)
    headless: bool = True
    idle_timeout_seconds: int = Field(default=600, ge=30, le=7200)


class NavigateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SelectorRequest(BaseModel):
    selector: str = Field(min_length=1, max_length=512)


class TypeRequest(BaseModel):
    selector: str = Field(min_length=1, max_length=512)
    value: str = Field(min_length=0, max_length=20_000)


class ClickRequest(BaseModel):
    selector: str = Field(min_length=1, max_length=512)
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class SubmitRequest(BaseModel):
    submit_selector: str = Field(min_length=1, max_length=512)
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class ActionLogView(BaseModel):
    id: str
    session_id: str
    action_type: str
    target: str
    args: dict[str, Any]
    status: str
    blocked_reason: str
    result_excerpt: str
    approval_id: str | None
    started_at: datetime
    completed_at: datetime | None


class GatedActionResponse(BaseModel):
    action: ActionLogView
    approval_id: str | None
    approval_decision: str


def _domain_view(d: BrowserAllowedDomain) -> AllowedDomainView:
    return AllowedDomainView(
        id=str(d.id), pattern=d.pattern, description=d.description,
        allow_form_submit=d.allow_form_submit, created_at=d.created_at,
    )


def _session_view(s: BrowserSession) -> SessionView:
    return SessionView(
        id=str(s.id),
        label=s.label,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        current_url=s.current_url,
        idle_timeout_seconds=s.idle_timeout_seconds,
        started_at=s.started_at,
        last_active_at=s.last_active_at,
        closed_at=s.closed_at,
        is_live=pw.get_live(str(s.id)) is not None,
    )


def _action_view(a: BrowserAction) -> ActionLogView:
    return ActionLogView(
        id=str(a.id),
        session_id=str(a.session_id),
        action_type=a.action_type.value,
        target=a.target,
        args=dict(a.args or {}),
        status=a.status.value,
        blocked_reason=a.blocked_reason,
        result_excerpt=a.result_excerpt,
        approval_id=str(a.approval_id) if a.approval_id else None,
        started_at=a.started_at,
        completed_at=a.completed_at,
    )


# ---- Status probe ---------------------------------------------------------


@router.get("/status")
async def status_probe(
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    return {
        "playwright_installed": pw.is_available(),
        "install_command": (
            "pip install -e .[automation] && python -m playwright install chromium"
        ),
        "live_sessions_in_process": len(pw._LIVE),  # noqa: SLF001
    }


# ---- Allow-list CRUD (admin only) -----------------------------------------


@router.get("/allowed-domains", response_model=list[AllowedDomainView])
async def list_allowed_domains(
    user: Annotated[User, Depends(get_current_user)],
) -> list[AllowedDomainView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(BrowserAllowedDomain)
            .where(BrowserAllowedDomain.user_id == user.id)
            .order_by(BrowserAllowedDomain.pattern)
        )
        return [_domain_view(d) for d in result.scalars()]


@router.post(
    "/allowed-domains",
    response_model=AllowedDomainView,
    status_code=status.HTTP_201_CREATED,
)
async def add_allowed_domain(
    body: AllowedDomainCreate, admin: Annotated[User, Depends(require_admin)]
) -> AllowedDomainView:
    d = BrowserAllowedDomain(
        user_id=admin.id,
        pattern=body.pattern,
        description=body.description,
        allow_form_submit=body.allow_form_submit,
    )
    async with get_sessionmaker()() as session:
        session.add(d)
        await session.commit()
        await session.refresh(d)
    return _domain_view(d)


@router.delete("/allowed-domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_allowed_domain(
    domain_id: uuid.UUID, admin: Annotated[User, Depends(require_admin)]
) -> None:
    async with get_sessionmaker()() as session:
        d = await session.get(BrowserAllowedDomain, domain_id)
        if d is None or d.user_id != admin.id:
            raise HTTPException(status_code=404, detail="domain not in allow-list")
        await session.delete(d)
        await session.commit()


# ---- Sessions -------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SessionView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(BrowserSession)
            .where(BrowserSession.user_id == user.id)
            .order_by(BrowserSession.started_at.desc())
            .limit(limit)
        )
        return [_session_view(s) for s in result.scalars()]


@router.post("/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
async def start_session_route(
    body: StartSessionRequest, user: Annotated[User, Depends(get_current_user)]
) -> SessionView:
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )
    try:
        result = await ba.start_session(
            ctx,
            label=body.label,
            headless=body.headless,
            idle_timeout_seconds=body.idle_timeout_seconds,
        )
    except ba.BrowserNotAvailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _session_view(result.session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_session_route(
    session_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        s = await session.get(BrowserSession, session_id)
        if s is None or s.user_id != user.id:
            raise HTTPException(status_code=404, detail="session not found")
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )
    await ba.stop_session(ctx, session_id)


# ---- Per-session actions --------------------------------------------------


def _ctx_for_user(user: User) -> AgentContext:
    return AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )


@router.post("/sessions/{session_id}/navigate", response_model=ActionLogView)
async def navigate_route(
    session_id: uuid.UUID, body: NavigateRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ActionLogView:
    try:
        row = await ba.navigate(_ctx_for_user(user), session_id, body.url)
    except PermissionError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return _action_view(row)


@router.post("/sessions/{session_id}/screenshot")
async def screenshot_route(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    full_page: bool = Query(default=False),
) -> Response:
    try:
        png, _ = await ba.screenshot(_ctx_for_user(user), session_id, full_page=full_page)
    except PermissionError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png")


@router.post("/sessions/{session_id}/extract", response_model=ActionLogView)
async def get_text_route(
    session_id: uuid.UUID, body: SelectorRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ActionLogView:
    try:
        row = await ba.get_text(_ctx_for_user(user), session_id, body.selector)
    except PermissionError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return _action_view(row)


@router.post("/sessions/{session_id}/click", response_model=GatedActionResponse)
async def click_route(
    session_id: uuid.UUID, body: ClickRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> GatedActionResponse:
    agent = ComputerControlAgent()
    ctx = _ctx_for_user(user)
    ctx.permission_level = body.permission_level
    try:
        row, outcome = await ba.request_click(agent, ctx, session_id, body.selector)
    except PermissionError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return GatedActionResponse(
        action=_action_view(row),
        approval_id=str(outcome.approval.id) if outcome and outcome.approval else None,
        approval_decision=outcome.decision.value if outcome else "allow",
    )


@router.post("/sessions/{session_id}/type", response_model=ActionLogView)
async def type_route(
    session_id: uuid.UUID, body: TypeRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ActionLogView:
    try:
        row = await ba.type_text(
            _ctx_for_user(user), session_id, body.selector, body.value
        )
    except PermissionError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return _action_view(row)


@router.post("/sessions/{session_id}/submit", response_model=GatedActionResponse)
async def submit_route(
    session_id: uuid.UUID, body: SubmitRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> GatedActionResponse:
    agent = ComputerControlAgent()
    ctx = _ctx_for_user(user)
    ctx.permission_level = body.permission_level
    try:
        row, outcome = await ba.request_submit(
            agent, ctx, session_id, body.submit_selector
        )
    except PermissionError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    return GatedActionResponse(
        action=_action_view(row),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


# ---- Action log -----------------------------------------------------------


@router.get("/sessions/{session_id}/actions", response_model=list[ActionLogView])
async def list_actions(
    session_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ActionLogView]:
    async with get_sessionmaker()() as session:
        s = await session.get(BrowserSession, session_id)
        if s is None or s.user_id != user.id:
            raise HTTPException(status_code=404, detail="session not found")
        result = await session.execute(
            select(BrowserAction)
            .where(BrowserAction.session_id == session_id)
            .order_by(BrowserAction.started_at.desc())
            .limit(limit)
        )
        return [_action_view(a) for a in result.scalars()]
