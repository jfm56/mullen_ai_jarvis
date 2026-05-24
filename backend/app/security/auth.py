"""Single-user authentication: Argon2id password + JWT sessions.

Phase 1: password verification + short-lived access tokens. A FastAPI
`get_current_user` dependency that resolves the bearer token to a User
row. Optional Windows Hello step-up for high-risk approvals lands later.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User

_HASHER = PasswordHasher()
_JWT_ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def hash_password(plaintext: str) -> str:
    return _HASHER.hash(plaintext)


def verify_password(plaintext: str, password_hash: str) -> bool:
    try:
        return _HASHER.verify(password_hash, plaintext)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _HASHER.check_needs_rehash(password_hash)


def issue_token(user_id: uuid.UUID, *, ttl_min: int | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    ttl = ttl_min if ttl_min is not None else settings.access_token_ttl_min
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "iss": "mullen_ai_jarvis",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token, settings.secret_key, algorithms=[_JWT_ALGORITHM], issuer="mullen_ai_jarvis"
        )
        return uuid.UUID(claims["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def _load_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_token(token)
    async with get_sessionmaker()() as session:
        user = await _load_user(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return user
