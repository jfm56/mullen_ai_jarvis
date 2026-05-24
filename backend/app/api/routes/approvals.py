"""Approvals API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.models import User
from app.security import approvals
from app.security.auth import get_current_user

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalView(BaseModel):
    id: str
    created_at: datetime
    decided_at: datetime | None
    expires_at: datetime | None
    agent: str
    domain: str
    action_class: str
    action_name: str
    target_summary: str
    preview: str
    payload: dict[str, Any]
    status: str
    decision_note: str
    request_id: str


def _to_view(a: Any) -> ApprovalView:
    return ApprovalView(
        id=str(a.id),
        created_at=a.created_at,
        decided_at=a.decided_at,
        expires_at=a.expires_at,
        agent=a.agent,
        domain=a.domain,
        action_class=a.action_class,
        action_name=a.action_name,
        target_summary=a.target_summary,
        preview=a.preview,
        payload=a.payload,
        status=a.status.value if hasattr(a.status, "value") else str(a.status),
        decision_note=a.decision_note,
        request_id=a.request_id,
    )


class DecisionRequest(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.get("", response_model=list[ApprovalView])
async def list_approvals(
    _: Annotated[User, Depends(get_current_user)],
    agent: str | None = Query(default=None),
    domain: str | None = Query(default=None),
) -> list[ApprovalView]:
    rows = await approvals.list_pending(agent=agent, domain=domain)
    return [_to_view(r) for r in rows]


@router.get("/{approval_id}", response_model=ApprovalView)
async def get_approval(
    approval_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
) -> ApprovalView:
    row = await approvals.get(approval_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")
    return _to_view(row)


@router.post("/{approval_id}/decision", response_model=ApprovalView)
async def decide_approval(
    approval_id: uuid.UUID,
    body: DecisionRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> ApprovalView:
    try:
        row = await approvals.decide(
            approval_id,
            approve=body.approve,
            decided_by=user.id,
            note=body.note,
        )
    except approvals.ApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _to_view(row)
