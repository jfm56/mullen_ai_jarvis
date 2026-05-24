"""Agent invocation routes.

Phase 2: only the Personal Assistant is wired up. Other agents are
added here as they ship.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents.base import AgentContext
from app.agents.personal_assistant import PersonalAssistantAgent
from app.db.models import User
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/agents", tags=["agents"])


class HandleRequest(BaseModel):
    input: str = Field(default="", max_length=10_000)
    domain: str = Field(default="personal", max_length=64)
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class HandleResponse(BaseModel):
    text: str
    metadata: dict[str, Any]


@router.post("/personal_assistant/handle", response_model=HandleResponse)
async def personal_assistant_handle(
    body: HandleRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> HandleResponse:
    agent = PersonalAssistantAgent()
    ctx = AgentContext(
        user_id=user.id,
        domain=body.domain,
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()),
        input_text=body.input,
        metadata={},
    )
    result = await agent.handle(ctx)
    return HandleResponse(text=result.text, metadata=result.metadata)
