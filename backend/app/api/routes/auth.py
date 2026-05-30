"""Login + current-user + Google OAuth start/callback endpoints."""

from __future__ import annotations

import secrets as stdlib_secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import OAuthAccount, User
from app.integrations import gmail, google_calendar, google_oauth
from app.security.auth import (
    get_current_user,
    hash_password,
    issue_token,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory CSRF state store. Single-user; we don't need a DB-backed one.
# Maps state -> (user_id, service, requested_at_iso).
_pending_oauth: dict[str, tuple[str, str, str]] = {}


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


# --- Google OAuth -----------------------------------------------------------


_SERVICES = {
    "gmail": ("gmail.readonly", gmail.SCOPES_READ),
    "gmail.send": ("gmail.send", gmail.SCOPES_READ + gmail.SCOPES_SEND),
    "calendar": ("calendar.readonly", google_calendar.SCOPES_READ),
    "calendar.write": (
        "calendar.events",
        google_calendar.SCOPES_READ + google_calendar.SCOPES_WRITE,
    ),
}


@router.get("/google/start", include_in_schema=True)
async def google_oauth_start(
    user: Annotated[User, Depends(get_current_user)],
    service: str = Query(default="gmail", description="gmail | gmail.send | calendar | calendar.write"),
) -> RedirectResponse:
    """Kick off the Google consent flow. Redirects the browser to Google."""
    if service not in _SERVICES:
        raise HTTPException(
            status_code=400, detail=f"unknown service '{service}'; valid: {list(_SERVICES)}"
        )
    _, scopes = _SERVICES[service]

    # CSRF token bound to this user + service.
    state = stdlib_secrets.token_urlsafe(32)
    _pending_oauth[state] = (
        str(user.id), service, datetime.now(timezone.utc).isoformat()
    )

    # Both Gmail and Calendar share the same authorize URL pattern;
    # build via the calendar helper which accepts any scope list.
    try:
        url = google_calendar.authorize_url(state=state, scopes=scopes)
    except google_calendar.GoogleCalendarError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return RedirectResponse(url, status_code=302)


@router.get("/google/callback", response_class=HTMLResponse, include_in_schema=False)
async def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(default=None),
) -> str:
    """Google redirects here after consent.

    Validates state, exchanges code, stores refresh token in keyring, and
    upserts an OAuthAccount row. Returns a small HTML page rather than a
    redirect so the user gets a clean success/error message even if the UI
    is closed.
    """
    if error:
        return _callback_html(success=False, message=f"Google returned error: {error}")

    pending = _pending_oauth.pop(state, None)
    if pending is None:
        return _callback_html(success=False, message="invalid or expired state — please retry from /auth/google/start")
    user_id_str, service, _ = pending

    try:
        tokens = await google_oauth.exchange_code(code)
        if not tokens.refresh_token:
            return _callback_html(
                success=False,
                message=(
                    "Google did not return a refresh_token. This usually means "
                    "you already authorized this app. Revoke at "
                    "https://myaccount.google.com/permissions and retry."
                ),
            )
        email = await google_oauth.fetch_user_email(tokens.access_token)
    except google_oauth.GoogleOAuthError as exc:
        return _callback_html(success=False, message=f"token exchange failed: {exc}")

    # Persist: keyring for the refresh token, DB row for the metadata.
    google_oauth.store_refresh_token(email, tokens.refresh_token)

    import uuid as _uuid

    user_uuid = _uuid.UUID(user_id_str)
    async with get_sessionmaker()() as session:
        existing = await session.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == user_uuid,
                OAuthAccount.provider == "google",
                OAuthAccount.account_email == email,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = OAuthAccount(
                user_id=user_uuid,
                provider="google",
                account_email=email,
                scopes=tokens.scope,
                access_token_expires_at=tokens.expires_at,
                revoked_at=None,
            )
            session.add(row)
        else:
            # Merge granted scopes — the user may extend over time.
            existing_scopes = set((row.scopes or "").split())
            existing_scopes.update(tokens.scope.split())
            row.scopes = " ".join(sorted(existing_scopes))
            row.access_token_expires_at = tokens.expires_at
            row.revoked_at = None
        await session.commit()

    return _callback_html(
        success=True,
        message=(
            f"Connected Google account '{email}' for service '{service}'. "
            "You can close this tab."
        ),
    )


def _callback_html(*, success: bool, message: str) -> str:
    color = "#1f7a4d" if success else "#b3261e"
    title = "Connected" if success else "Connection failed"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Jarvis · Google OAuth · {title}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif;
           max-width: 540px; margin: 4rem auto; padding: 0 1rem;
           color: #1d2e39; line-height: 1.5; }}
    h1 {{ color: {color}; font-size: 1.2rem; }}
    p {{ font-size: 0.95rem; }}
    code {{ background: #eef; padding: 0.05rem 0.3rem; border-radius: 3px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p>{message}</p>
  <p><a href="/docs">Back to API docs</a></p>
</body>
</html>
"""
