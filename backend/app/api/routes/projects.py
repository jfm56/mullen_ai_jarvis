"""Projects + ProjectNotes API + weekly report.

Route ordering: static /weekly-report comes before /{project_id} so the
UUID parser doesn't try to swallow it.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from app.agents.base import AgentContext
from app.agents.project_manager import ProjectManagerAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    Project,
    ProjectNote,
    ProjectNoteKind,
    ProjectStatus,
    User,
    Vertical,
)
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/projects", tags=["projects"])


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.lower()).strip("-")
    return s[:120] or "project"


class ProjectView(BaseModel):
    id: str
    name: str
    slug: str
    client: str
    vertical: str
    status: str
    priority: int
    description: str
    value_estimate: float
    start_date: datetime | None
    target_end_date: datetime | None
    actual_end_date: datetime | None
    created_at: datetime
    updated_at: datetime
    # Computed: tasks tagged '#project:<slug>' in their notes field
    completed_tasks: int = 0
    total_tasks: int = 0
    percent_complete: float = 0.0


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    client: str = Field(default="", max_length=255)
    vertical: Vertical = Vertical.other
    status: ProjectStatus = ProjectStatus.active
    priority: int = Field(default=3, ge=1, le=5)
    description: str = Field(default="", max_length=10_000)
    value_estimate: float = 0.0
    start_date: datetime | None = None
    target_end_date: datetime | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    client: str | None = Field(default=None, max_length=255)
    vertical: Vertical | None = None
    status: ProjectStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    description: str | None = Field(default=None, max_length=10_000)
    value_estimate: float | None = None
    target_end_date: datetime | None = None
    actual_end_date: datetime | None = None


class ProjectNoteView(BaseModel):
    id: str
    kind: str
    text: str
    created_at: datetime


class ProjectNoteCreate(BaseModel):
    kind: ProjectNoteKind = ProjectNoteKind.log
    text: str = Field(min_length=1, max_length=10_000)


def _to_view(p: Project, *, completed: int = 0, total: int = 0) -> ProjectView:
    pct = (completed / total * 100.0) if total > 0 else 0.0
    return ProjectView(
        id=str(p.id),
        name=p.name,
        slug=p.slug,
        client=p.client,
        vertical=p.vertical.value,
        status=p.status.value,
        priority=p.priority,
        description=p.description,
        value_estimate=p.value_estimate,
        start_date=p.start_date,
        target_end_date=p.target_end_date,
        actual_end_date=p.actual_end_date,
        created_at=p.created_at,
        updated_at=p.updated_at,
        completed_tasks=completed,
        total_tasks=total,
        percent_complete=round(pct, 1),
    )


async def _task_counts_for_slugs(
    session, user_id, slugs: list[str]
) -> dict[str, tuple[int, int]]:
    """Return {slug: (completed_count, total_count)} for the given slugs.

    Tasks associate with projects via a '#project:<slug>' marker in the
    task `notes` field. One query handles all projects in a batch.
    """
    from app.db.models import Task, TaskStatus

    if not slugs:
        return {}
    counts: dict[str, tuple[int, int]] = {}
    # SQL LIKE on each slug. One query per project (small N for a single user).
    for slug in slugs:
        marker = f"#project:{slug}"
        result = await session.execute(
            select(
                func.count(Task.id).label("total"),
                func.sum(
                    case((Task.status == TaskStatus.done, 1), else_=0)
                ).label("completed"),
            ).where(
                Task.user_id == user_id,
                Task.notes.contains(marker),
            )
        )
        row = result.one()
        counts[slug] = (int(row.completed or 0), int(row.total or 0))
    return counts


def _to_note_view(n: ProjectNote) -> ProjectNoteView:
    return ProjectNoteView(
        id=str(n.id),
        kind=n.kind.value,
        text=n.text,
        created_at=n.created_at,
    )


@router.get("", response_model=list[ProjectView])
async def list_projects(
    user: Annotated[User, Depends(get_current_user)],
    project_status: ProjectStatus | None = Query(default=None, alias="status"),
    vertical: Vertical | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ProjectView]:
    stmt = (
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.priority, Project.updated_at.desc())
        .limit(limit)
    )
    if project_status:
        stmt = stmt.where(Project.status == project_status)
    if vertical:
        stmt = stmt.where(Project.vertical == vertical)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        projects = list(result.scalars())
        counts = await _task_counts_for_slugs(
            session, user.id, [p.slug for p in projects]
        )
        return [
            _to_view(p, completed=counts.get(p.slug, (0, 0))[0],
                     total=counts.get(p.slug, (0, 0))[1])
            for p in projects
        ]


@router.post("", response_model=ProjectView, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, user: Annotated[User, Depends(get_current_user)]
) -> ProjectView:
    project = Project(
        user_id=user.id,
        name=body.name,
        slug=_slugify(body.name),
        client=body.client,
        vertical=body.vertical,
        status=body.status,
        priority=body.priority,
        description=body.description,
        value_estimate=body.value_estimate,
        start_date=body.start_date,
        target_end_date=body.target_end_date,
    )
    async with get_sessionmaker()() as session:
        # Resolve slug collision by appending a numeric suffix.
        base = project.slug
        suffix = 1
        while True:
            existing = await session.execute(
                select(Project).where(
                    Project.user_id == user.id, Project.slug == project.slug
                )
            )
            if existing.scalar_one_or_none() is None:
                break
            suffix += 1
            project.slug = f"{base}-{suffix}"
        session.add(project)
        await session.commit()
        await session.refresh(project)
    return _to_view(project)


@router.get("/weekly-report", response_model=dict)
async def weekly_report(
    user: Annotated[User, Depends(get_current_user)],
    domain: str = Query(default="business"),
) -> dict:
    agent = ProjectManagerAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain=domain,
        permission_level=PermissionLevel.read_only,
        request_id=str(uuid.uuid4()),
        input_text="",
        metadata={},
    )
    text = await agent.weekly_report(ctx)
    return {"text": text}


@router.get("/{project_id}", response_model=ProjectView)
async def get_project(
    project_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> ProjectView:
    async with get_sessionmaker()() as session:
        p = await session.get(Project, project_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="project not found")
        counts = await _task_counts_for_slugs(session, user.id, [p.slug])
        c, t = counts.get(p.slug, (0, 0))
        return _to_view(p, completed=c, total=t)


@router.patch("/{project_id}", response_model=ProjectView)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectView:
    async with get_sessionmaker()() as session:
        p = await session.get(Project, project_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="project not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(p, field_name, value)
        await session.commit()
        await session.refresh(p)
        counts = await _task_counts_for_slugs(session, user.id, [p.slug])
        c, t = counts.get(p.slug, (0, 0))
        return _to_view(p, completed=c, total=t)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        p = await session.get(Project, project_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="project not found")
        await session.delete(p)
        await session.commit()


@router.get("/{project_id}/notes", response_model=list[ProjectNoteView])
async def list_notes(
    project_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> list[ProjectNoteView]:
    async with get_sessionmaker()() as session:
        p = await session.get(Project, project_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="project not found")
        result = await session.execute(
            select(ProjectNote)
            .where(ProjectNote.project_id == project_id)
            .order_by(ProjectNote.created_at.desc())
        )
        return [_to_note_view(n) for n in result.scalars()]


@router.post(
    "/{project_id}/notes",
    response_model=ProjectNoteView,
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    project_id: uuid.UUID,
    body: ProjectNoteCreate,
    user: Annotated[User, Depends(get_current_user)],
) -> ProjectNoteView:
    async with get_sessionmaker()() as session:
        p = await session.get(Project, project_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="project not found")
        note = ProjectNote(project_id=project_id, kind=body.kind, text=body.text)
        session.add(note)
        await session.commit()
        await session.refresh(note)
        return _to_note_view(note)
