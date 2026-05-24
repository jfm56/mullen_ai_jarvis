"""Login + current-user endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import User
from app.security.auth import (
    get_current_user,
    hash_password,
    issue_token,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: str
    username: str
    display_name: str
    is_admin: bool


@router.post("/login", response_model=TokenResponse)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenResponse:
    async with get_sessionmaker()() as session:
        result = await session.execute(select(User).where(User.username == form.username))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(form.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
            )

        # Opportunistic rehash if Argon2 parameters were upgraded since this user
        # was created.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(form.password)
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()

        return TokenResponse(access_token=issue_token(user.id))


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )
