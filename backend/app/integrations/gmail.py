"""Gmail integration.

Architecture mirrors `google_calendar.py`:
  * OAuth client_id from env GOOGLE_OAUTH_CLIENT_ID (non-secret)
  * client_secret + per-account refresh tokens in OS keyring
  * OAuthAccount row tracks granted scopes + token expiry

Scope strategy:
  * Initial connect: gmail.readonly  (Phase 4 main use case)
  * Send scope (gmail.send) is requested SEPARATELY when the user first
    approves an action that needs it — keeps the principle-of-least-privilege
    explicit instead of grabbing send on day one.

Tests cover URL building and header parsing; live API calls are deferred.
"""

from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Email, EmailDirection

PROVIDER = "google"  # OAuthAccount.provider value
SCOPES_READ = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES_SEND = ["https://www.googleapis.com/auth/gmail.send"]

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


class GmailError(RuntimeError):
    pass


def _client_id() -> str:
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    if not cid:
        raise GmailError("GOOGLE_OAUTH_CLIENT_ID not configured")
    return cid


def _redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_OAUTH_REDIRECT", "http://127.0.0.1:8000/auth/google/callback"
    )


def authorize_url(*, state: str, include_send: bool = False) -> str:
    """Build the consent URL.

    `include_send=True` requests both read and send scopes — used the first
    time an approved send-class action runs and discovers it needs send.
    """
    scopes = list(SCOPES_READ)
    if include_send:
        scopes += SCOPES_SEND
    return _AUTH_URL + "?" + urlencode(
        {
            "client_id": _client_id(),
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "include_granted_scopes": "true",
        }
    )


# --- Message parsing --------------------------------------------------------


def _header(headers: list[dict[str, str]], name: str) -> str:
    needle = name.lower()
    for h in headers:
        if h.get("name", "").lower() == needle:
            return h.get("value", "")
    return ""


def _decode_body(data: str) -> str:
    """Gmail returns base64url-encoded body data."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _extract_body_text(payload: dict[str, Any]) -> str:
    """Walk a Gmail payload tree and return the text/plain part."""
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode_body((payload.get("body") or {}).get("data", ""))
    for part in payload.get("parts", []) or []:
        text = _extract_body_text(part)
        if text:
            return text
    # If no text/plain part, fall back to top-level body if present.
    return _decode_body((payload.get("body") or {}).get("data", ""))


def parse_message(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert one Gmail messages.get response into our column shape."""
    payload = raw.get("payload") or {}
    headers = payload.get("headers") or []

    received_str = _header(headers, "Date") or _header(headers, "Received")
    try:
        received_at = parsedate_to_datetime(received_str) if received_str else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        received_at = datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)

    return {
        "external_id": raw.get("id", ""),
        "thread_id": raw.get("threadId"),
        "labels": raw.get("labelIds", []) or [],
        "snippet": raw.get("snippet", ""),
        "from_addr": _header(headers, "From"),
        "to_addrs": _header(headers, "To"),
        "cc_addrs": _header(headers, "Cc"),
        "subject": _header(headers, "Subject"),
        "received_at": received_at,
        "body_text": _extract_body_text(payload),
    }


# --- DB upsert --------------------------------------------------------------


async def upsert_email(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    raw: dict[str, Any],
    domain: str = "personal",
) -> Email:
    """Insert or update one email, idempotent on (source='gmail', external_id)."""
    parsed = parse_message(raw)
    if not parsed["external_id"]:
        raise GmailError("message has no id")

    result = await session.execute(
        select(Email).where(
            Email.source == "gmail",
            Email.external_id == parsed["external_id"],
        )
    )
    email = result.scalar_one_or_none()
    if email is None:
        email = Email(
            user_id=user_id,
            source="gmail",
            domain=domain,
            direction=EmailDirection.inbound,
            raw=raw,
            **parsed,
        )
        session.add(email)
    else:
        for k, v in parsed.items():
            setattr(email, k, v)
        email.raw = raw
        email.synced_at = datetime.now(timezone.utc)
    return email


# --- Sync ------------------------------------------------------------------


_GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


async def sync_recent_emails(
    *,
    user_id: uuid.UUID,
    account_email: str,
    days: int = 7,
    max_messages: int = 100,
    domain: str = "personal",
) -> int:
    """Pull recent inbox messages for `account_email` and upsert each.

    Returns the number of messages synced. Uses the stored OAuth refresh
    token (in keyring) to get a fresh access token. Each message is also
    enriched (scam + categorize) by the Email Assistant so it shows up
    triaged in /emails.
    """
    import httpx

    from app.agents.email_assistant import EmailAssistantAgent
    from app.db.base import get_sessionmaker
    from app.integrations import google_oauth

    access_token = await google_oauth.access_token_for(account_email)

    # Gmail query: inbox, last N days.
    query = f"in:inbox newer_than:{days}d"
    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {access_token}"}
    ) as client:
        # List message ids first.
        resp = await client.get(
            f"{_GMAIL_API}/users/me/messages",
            params={"q": query, "maxResults": min(max_messages, 100)},
        )
        if resp.status_code >= 400:
            raise GmailError(f"messages.list failed: {resp.status_code} {resp.text[:200]}")
        ids = [m["id"] for m in (resp.json().get("messages") or [])]
        if not ids:
            return 0

        # Then fetch each in full. `format=full` returns headers + body parts.
        synced = 0
        agent = EmailAssistantAgent()
        async with get_sessionmaker()() as session:
            for msg_id in ids:
                msg_resp = await client.get(
                    f"{_GMAIL_API}/users/me/messages/{msg_id}",
                    params={"format": "full"},
                )
                if msg_resp.status_code >= 400:
                    continue
                raw = msg_resp.json()
                email = await upsert_email(
                    session, user_id=user_id, raw=raw, domain=domain
                )
                # Enrich (scam + categorize). Inline so the user sees triage
                # on the very next /emails call.
                try:
                    await agent.enrich(email)
                except Exception:  # noqa: BLE001 - never block sync on enrich
                    pass
                synced += 1
            await session.commit()
        return synced


# --- Send -------------------------------------------------------------------


async def send_message(
    *,
    account_email: str,
    to: str,
    subject: str,
    body_text: str,
) -> str:
    """Send a plain-text email via the Gmail API as `account_email`.

    Returns the sent Gmail message id. Requires the `gmail.send` scope to have
    been granted for `account_email` (refresh token in keyring via the OAuth
    flow). Raises GmailError if the account isn't connected or the API rejects.
    """
    import httpx

    from app.integrations import google_oauth

    if not (to or "").strip():
        raise GmailError("no recipient address")

    try:
        access_token = await google_oauth.access_token_for(account_email)
    except google_oauth.GoogleOAuthError as exc:
        raise GmailError(str(exc)) from exc

    message = EmailMessage()
    message["To"] = to
    message["From"] = account_email
    message["Subject"] = subject
    message.set_content(body_text)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    async with httpx.AsyncClient(
        timeout=30.0, headers={"Authorization": f"Bearer {access_token}"}
    ) as client:
        resp = await client.post(
            f"{_GMAIL_API}/users/me/messages/send", json={"raw": raw}
        )
    if resp.status_code >= 400:
        raise GmailError(f"gmail send failed: {resp.status_code} {resp.text[:200]}")
    return resp.json().get("id", "")
