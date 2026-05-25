"""Computer Control API — admin-only allow-list CRUD + gated execution.

Adding apps/scripts is admin-only at the route level. Executing them
requires a previously-approved Approval row.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.computer_control import ComputerControlAgent, DestructiveConfirmationRequired
from app.db.base import get_sessionmaker
from app.db.models import (
    AllowedApp,
    AllowedScript,
    ComputerActionLog,
    User,
)
from app.integrations.computer import (
    app_launcher,
    file_hash,
    file_ops,
    safe_path,
    script_runner,
)
from app.security.auth import get_current_user, require_admin
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/computer", tags=["computer"])


# ---- Views ----------------------------------------------------------------


class AppView(BaseModel):
    id: str
    name: str
    path: str
    args_template: str
    description: str
    hash_required: bool
    expected_hash: str
    created_at: datetime


class AppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    args_template: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=2000)
    hash_required: bool = False


class ScriptView(BaseModel):
    id: str
    name: str
    path: str
    interpreter: str
    args_template: str
    description: str
    sha256_hash: str
    created_at: datetime


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    interpreter: str = Field(default="", max_length=255)
    args_template: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=2000)


class ActionLogView(BaseModel):
    id: str
    action_type: str
    target: str
    args: str
    status: str
    return_code: int | None
    stdout_excerpt: str
    stderr_excerpt: str
    blocked_reason: str
    approval_id: str | None
    started_at: datetime
    completed_at: datetime | None


class FileEntryView(BaseModel):
    path: str
    is_dir: bool
    size: int
    modified: float


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=255)
    root: str | None = None
    max_results: int = Field(default=50, ge=1, le=200)


class ReadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class LaunchRequest(BaseModel):
    app_id: uuid.UUID
    user_args: str = Field(default="", max_length=2000)
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class RunScriptRequest(BaseModel):
    script_id: uuid.UUID
    user_args: str = Field(default="", max_length=2000)
    destructive: bool = False
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class GatedActionResponse(BaseModel):
    action_id: str
    approval_id: str | None
    approval_decision: str


class ExecuteRequest(BaseModel):
    approval_id: uuid.UUID


class ExecuteResponse(BaseModel):
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool


def _app_view(a: AllowedApp) -> AppView:
    return AppView(
        id=str(a.id), name=a.name, path=a.path,
        args_template=a.args_template, description=a.description,
        hash_required=a.hash_required, expected_hash=a.expected_hash,
        created_at=a.created_at,
    )


def _script_view(s: AllowedScript) -> ScriptView:
    return ScriptView(
        id=str(s.id), name=s.name, path=s.path,
        interpreter=s.interpreter, args_template=s.args_template,
        description=s.description, sha256_hash=s.sha256_hash,
        created_at=s.created_at,
    )


def _log_view(L: ComputerActionLog) -> ActionLogView:
    return ActionLogView(
        id=str(L.id),
        action_type=L.action_type.value,
        target=L.target,
        args=L.args,
        status=L.status.value,
        return_code=L.return_code,
        stdout_excerpt=L.stdout_excerpt,
        stderr_excerpt=L.stderr_excerpt,
        blocked_reason=L.blocked_reason,
        approval_id=str(L.approval_id) if L.approval_id else None,
        started_at=L.started_at,
        completed_at=L.completed_at,
    )


# ---- Allow-list CRUD (admin only) -----------------------------------------


@router.get("/apps", response_model=list[AppView])
async def list_apps(user: Annotated[User, Depends(get_current_user)]) -> list[AppView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(AllowedApp).where(AllowedApp.user_id == user.id).order_by(AllowedApp.name)
        )
        return [_app_view(a) for a in result.scalars()]


@router.post("/apps", response_model=AppView, status_code=status.HTTP_201_CREATED)
async def add_app(
    body: AppCreate, admin: Annotated[User, Depends(require_admin)]
) -> AppView:
    # Validate the path resolves to an existing file inside allowed roots.
    try:
        resolved = safe_path.resolve_safe(body.path, must_exist=True)
    except safe_path.UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=f"unsafe path: {exc}") from exc
    expected_hash = ""
    if body.hash_required:
        try:
            expected_hash = file_hash.sha256_of(resolved)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"could not hash file: {exc}") from exc
    app_row = AllowedApp(
        user_id=admin.id,
        name=body.name,
        path=str(resolved),
        args_template=body.args_template,
        description=body.description,
        hash_required=body.hash_required,
        expected_hash=expected_hash,
    )
    async with get_sessionmaker()() as session:
        session.add(app_row)
        await session.commit()
        await session.refresh(app_row)
    return _app_view(app_row)


@router.delete("/apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app(
    app_id: uuid.UUID, admin: Annotated[User, Depends(require_admin)]
) -> None:
    async with get_sessionmaker()() as session:
        row = await session.get(AllowedApp, app_id)
        if row is None or row.user_id != admin.id:
            raise HTTPException(status_code=404, detail="app not found")
        await session.delete(row)
        await session.commit()


@router.get("/scripts", response_model=list[ScriptView])
async def list_scripts(user: Annotated[User, Depends(get_current_user)]) -> list[ScriptView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(AllowedScript).where(AllowedScript.user_id == user.id).order_by(AllowedScript.name)
        )
        return [_script_view(s) for s in result.scalars()]


@router.post("/scripts", response_model=ScriptView, status_code=status.HTTP_201_CREATED)
async def add_script(
    body: ScriptCreate, admin: Annotated[User, Depends(require_admin)]
) -> ScriptView:
    try:
        resolved = safe_path.resolve_safe(body.path, must_exist=True)
    except safe_path.UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=f"unsafe path: {exc}") from exc
    try:
        hash_hex = file_hash.sha256_of(resolved)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"could not hash file: {exc}") from exc

    s = AllowedScript(
        user_id=admin.id,
        name=body.name,
        path=str(resolved),
        interpreter=body.interpreter,
        args_template=body.args_template,
        description=body.description,
        sha256_hash=hash_hex,
    )
    async with get_sessionmaker()() as session:
        session.add(s)
        await session.commit()
        await session.refresh(s)
    return _script_view(s)


@router.delete("/scripts/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_script(
    script_id: uuid.UUID, admin: Annotated[User, Depends(require_admin)]
) -> None:
    async with get_sessionmaker()() as session:
        row = await session.get(AllowedScript, script_id)
        if row is None or row.user_id != admin.id:
            raise HTTPException(status_code=404, detail="script not found")
        await session.delete(row)
        await session.commit()


# ---- Action history -------------------------------------------------------


@router.get("/actions", response_model=list[ActionLogView])
async def list_actions(
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ActionLogView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(ComputerActionLog)
            .where(ComputerActionLog.user_id == user.id)
            .order_by(ComputerActionLog.started_at.desc())
            .limit(limit)
        )
        return [_log_view(L) for L in result.scalars()]


@router.get("/roots", response_model=list[str])
async def list_roots(_: Annotated[User, Depends(get_current_user)]) -> list[str]:
    return [str(r) for r in safe_path.allowed_roots()]


# ---- Read-only file ops ---------------------------------------------------


@router.post("/search", response_model=list[FileEntryView])
async def search(
    body: SearchRequest, user: Annotated[User, Depends(get_current_user)]
) -> list[FileEntryView]:
    agent = ComputerControlAgent()
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.read_only,
        request_id=str(uuid.uuid4()), input_text=body.query, metadata={},
    )
    try:
        results = await agent.search_files(
            ctx, query=body.query, root=body.root, max_results=body.max_results
        )
    except safe_path.UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [FileEntryView(path=r.path, is_dir=r.is_dir, size=r.size, modified=r.modified) for r in results]


@router.post("/read", response_model=dict)
async def read(
    body: ReadRequest, user: Annotated[User, Depends(get_current_user)]
) -> dict:
    agent = ComputerControlAgent()
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.read_only,
        request_id=str(uuid.uuid4()), input_text=body.path, metadata={},
    )
    try:
        text = await agent.read_text(ctx, path=body.path)
    except safe_path.UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": body.path, "text": text}


# ---- Gated execution ------------------------------------------------------


@router.post("/launch-app", response_model=GatedActionResponse)
async def request_launch_app(
    body: LaunchRequest, user: Annotated[User, Depends(get_current_user)]
) -> GatedActionResponse:
    async with get_sessionmaker()() as session:
        app_row = await session.get(AllowedApp, body.app_id)
        if app_row is None or app_row.user_id != user.id:
            raise HTTPException(status_code=404, detail="app not in allow-list")

    agent = ComputerControlAgent()
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()), input_text=body.user_args, metadata={},
    )
    log, outcome = await agent.request_launch_app(ctx, app=app_row, user_args=body.user_args)
    return GatedActionResponse(
        action_id=str(log.id),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


@router.post("/run-script", response_model=GatedActionResponse)
async def request_run_script(
    body: RunScriptRequest, user: Annotated[User, Depends(get_current_user)]
) -> GatedActionResponse:
    async with get_sessionmaker()() as session:
        script_row = await session.get(AllowedScript, body.script_id)
        if script_row is None or script_row.user_id != user.id:
            raise HTTPException(status_code=404, detail="script not in allow-list")

    agent = ComputerControlAgent()
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()), input_text=body.user_args, metadata={},
    )
    log, outcome = await agent.request_run_script(
        ctx, script=script_row, user_args=body.user_args, destructive=body.destructive
    )
    return GatedActionResponse(
        action_id=str(log.id),
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


@router.post("/launch-app/{app_id}/execute", response_model=ExecuteResponse)
async def execute_launch_app(
    app_id: uuid.UUID, body: ExecuteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ExecuteResponse:
    async with get_sessionmaker()() as session:
        app_row = await session.get(AllowedApp, app_id)
        if app_row is None or app_row.user_id != user.id:
            raise HTTPException(status_code=404, detail="app not in allow-list")
    agent = ComputerControlAgent()
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )
    try:
        result = await agent.execute_launch_app(
            ctx, app=app_row, approval_id=body.approval_id
        )
    except (PermissionError, app_launcher.AppLaunchError,
            file_hash.HashMismatchError, safe_path.UnsafePathError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ExecuteResponse(
        return_code=result.return_code, stdout=result.stdout,
        stderr=result.stderr, timed_out=result.timed_out,
    )


@router.post("/run-script/{script_id}/execute", response_model=ExecuteResponse)
async def execute_run_script(
    script_id: uuid.UUID, body: ExecuteRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ExecuteResponse:
    async with get_sessionmaker()() as session:
        script_row = await session.get(AllowedScript, script_id)
        if script_row is None or script_row.user_id != user.id:
            raise HTTPException(status_code=404, detail="script not in allow-list")
    agent = ComputerControlAgent()
    ctx = AgentContext(
        user_id=user.id, domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )
    try:
        result = await agent.execute_run_script(
            ctx, script=script_row, approval_id=body.approval_id
        )
    except DestructiveConfirmationRequired as exc:
        # 412 = Precondition Failed — the user must add the typed phrase to the approval note.
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    except (PermissionError, script_runner.ScriptRunError,
            file_hash.HashMismatchError, safe_path.UnsafePathError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return ExecuteResponse(
        return_code=result.return_code, stdout=result.stdout,
        stderr=result.stderr, timed_out=result.timed_out,
    )
