"""Backups API — admin-only.

POST /backups: triggers a synchronous pg_dump + encrypt. Returns the
BackupRecord row. (A future async-job version can land when RQ exists.)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import BackupKind, BackupRecord, BackupStatus, User
from app.integrations import backup as backup_svc
from app.integrations.computer import safe_path
from app.security.auth import require_admin

router = APIRouter(prefix="/backups", tags=["backups"])


class BackupView(BaseModel):
    id: str
    kind: str
    status: str
    file_path: str
    file_size: int
    sha256_hash: str
    encryption_alg: str
    key_id: str
    failure_reason: str
    started_at: datetime
    completed_at: datetime | None


class BackupCreate(BaseModel):
    output_dir: str = Field(min_length=1, max_length=1024)
    kind: BackupKind = BackupKind.full


def _to_view(b: BackupRecord) -> BackupView:
    return BackupView(
        id=str(b.id),
        kind=b.kind.value,
        status=b.status.value,
        file_path=b.file_path,
        file_size=b.file_size,
        sha256_hash=b.sha256_hash,
        encryption_alg=b.encryption_alg,
        key_id=b.key_id,
        failure_reason=b.failure_reason,
        started_at=b.started_at,
        completed_at=b.completed_at,
    )


@router.get("", response_model=list[BackupView])
async def list_backups(
    admin: Annotated[User, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[BackupView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(BackupRecord)
            .where(BackupRecord.user_id == admin.id)
            .order_by(BackupRecord.started_at.desc())
            .limit(limit)
        )
        return [_to_view(b) for b in result.scalars()]


@router.post("", response_model=BackupView, status_code=status.HTTP_201_CREATED)
async def create_backup(
    body: BackupCreate, admin: Annotated[User, Depends(require_admin)]
) -> BackupView:
    # Validate output_dir up front so we don't insert a row for an unsafe path.
    try:
        safe_path.resolve_safe(body.output_dir)
    except safe_path.UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=f"unsafe output_dir: {exc}") from exc

    record = BackupRecord(
        user_id=admin.id, kind=body.kind, status=BackupStatus.in_progress,
        file_path="",
    )
    async with get_sessionmaker()() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)

    try:
        result = await backup_svc.create_backup(output_dir=body.output_dir)
    except backup_svc.BackupError as exc:
        async with get_sessionmaker()() as session:
            row = await session.get(BackupRecord, record.id)
            row.status = BackupStatus.failed
            row.failure_reason = str(exc)
            row.completed_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(row)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async with get_sessionmaker()() as session:
        row = await session.get(BackupRecord, record.id)
        row.status = BackupStatus.completed
        row.file_path = str(result.path)
        row.file_size = result.bytes_written
        row.sha256_hash = result.sha256
        row.completed_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        return _to_view(row)


@router.get("/{backup_id}", response_model=BackupView)
async def get_backup(
    backup_id: uuid.UUID, admin: Annotated[User, Depends(require_admin)]
) -> BackupView:
    async with get_sessionmaker()() as session:
        b = await session.get(BackupRecord, backup_id)
        if b is None or b.user_id != admin.id:
            raise HTTPException(status_code=404, detail="backup not found")
        return _to_view(b)
