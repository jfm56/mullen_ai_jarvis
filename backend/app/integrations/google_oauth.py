"""Google OAuth 2.0 token exchange + refresh + userinfo.

Shared by `gmail.py` and `google_calendar.py`. The flow:

  1. UI (or curl) hits GET /auth/google/start?service=...&user_id=...
     The backend builds the Google consent URL (via the per-service
     `authorize_url` builder) and 302s the browser to Google.

  2. User grants consent. Google redirects to
     GET /auth/google/callback?code=...&state=...

  3. Callback validates state, calls `exchange_code(code)` here,
     calls `fetch_user_email(access_token)`, stores the refresh token
     in the OS keyring under
         oauth_refresh:google:{account_email}
     and upserts an `OAuthAccount` row recording which scopes were
     granted and when the access token expires.

  4. Sync jobs later call `access_token_for(account_email)` which
     transparently refreshes if expired.

  This module has zero DB dependencies — it's the pure HTTP layer.
  The route layer in `app/api/routes/auth.py` wires it to the DB.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.security import secrets

_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - public endpoint
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_PROVIDER = "google"


class GoogleOAuthError(RuntimeError):
    pass


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scope: str


def _client_id() -> str:
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not cid:
        raise GoogleOAuthError("GOOGLE_OAUTH_CLIENT_ID env var not set")
    return cid


def _client_secret() -> str:
    """Pull from keyring first (recommended), env as dev fallback."""
    try:
        return secrets.get_secret("google_oauth_client_secret", env_var="GOOGLE_OAUTH_CLIENT_SECRET")
    except secrets.SecretNotFoundError as exc:
        raise GoogleOAuthError(
            "google_oauth_client_secret not in keyring. Store it once with:\n"
            "  python -c \"from app.security.secrets import set_secret; "
            "set_secret('google_oauth_client_secret', '<paste-secret>')\""
        ) from exc


def _redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_OAUTH_REDIRECT", "http://127.0.0.1:8000/auth/google/callback"
    )


def _keyring_key(email: str) -> str:
    return f"oauth_refresh:{_PROVIDER}:{email.lower()}"


# --- HTTP calls (mockable in tests) -----------------------------------------


async def _post(url: str, data: dict[str, str], *, timeout: float = 15.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, data=data)
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400:
            raise GoogleOAuthError(
                f"google oauth call failed: {resp.status_code} {payload or resp.text[:200]}"
            )
        return payload


async def _get(url: str, *, token: str, timeout: float = 15.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400:
            raise GoogleOAuthError(
                f"google call failed: {resp.status_code} {payload or resp.text[:200]}"
            )
        return payload


# --- Token operations -------------------------------------------------------


def _parse_token_response(payload: dict) -> TokenSet:
    access_token = payload.get("access_token")
    if not access_token:
        raise GoogleOAuthError(f"no access_token in response: keys={list(payload.keys())}")
    expires_in = int(payload.get("expires_in", 3600))
    return TokenSet(
        access_token=access_token,
        refresh_token=payload.get("refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 30)),
        scope=payload.get("scope", ""),
    )


async def exchange_code(code: str) -> TokenSet:
    """Trade the one-time `code` for an access+refresh token pair."""
    payload = await _post(
        _TOKEN_URL,
        {
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": _redirect_uri(),
            "grant_type": "authorization_code",
        },
    )
    return _parse_token_response(payload)


async def refresh_access_token(refresh_token: str) -> TokenSet:
    """Mint a new access token. Google sometimes returns a new refresh
    token; if so, the caller should rotate it in the keyring."""
    payload = await _post(
        _TOKEN_URL,
        {
            "refresh_token": refresh_token,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "grant_type": "refresh_token",
        },
    )
    return _parse_token_response(payload)


async def fetch_user_email(access_token: str) -> str:
    """Resolve which Google account this access token belongs to."""
    payload = await _get(_USERINFO_URL, token=access_token)
    email = payload.get("email")
    if not email:
        raise GoogleOAuthError(f"userinfo had no email: keys={list(payload.keys())}")
    return email


# --- Keyring helpers --------------------------------------------------------


def store_refresh_token(email: str, refresh_token: str) -> None:
    secrets.set_secret(_keyring_key(email), refresh_token)


def load_refresh_token(email: str) -> str:
    try:
        return secrets.get_secret(_keyring_key(email))
    except secrets.SecretNotFoundError as exc:
        raise GoogleOAuthError(
            f"no refresh token in keyring for {email}. Run the OAuth flow first."
        ) from exc


def delete_refresh_token(email: str) -> None:
    secrets.delete_secret(_keyring_key(email))


# --- High-level: give me a usable access token for this account ------------


async def access_token_for(email: str) -> str:
    """Return a fresh access token for `email`. Refreshes if needed.

    This is what the sync jobs call. It hides the refresh dance.
    """
    refresh = load_refresh_token(email)
    tokens = await refresh_access_token(refresh)
    # Rotate stored refresh token if Google issued a new one.
    if tokens.refresh_token and tokens.refresh_token != refresh:
        store_refresh_token(email, tokens.refresh_token)
    return tokens.access_token
