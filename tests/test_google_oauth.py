"""Google OAuth: token exchange parser + keyring round-trip + refresh."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.integrations import google_oauth


def test_parse_token_response_sets_expiry(monkeypatch) -> None:
    fixed_now = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)

    class FakeDT:
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(google_oauth, "datetime", FakeDT)

    tokens = google_oauth._parse_token_response({
        "access_token": "ya29.abc",
        "refresh_token": "1//refresh",
        "expires_in": 3600,
        "scope": "gmail.readonly calendar.readonly",
    })
    assert tokens.access_token == "ya29.abc"
    assert tokens.refresh_token == "1//refresh"
    assert tokens.scope.startswith("gmail.readonly")
    # 3600s minus 30s safety margin = 3570s.
    delta = (tokens.expires_at - fixed_now).total_seconds()
    assert 3500 <= delta <= 3600


def test_parse_token_response_rejects_missing_access_token() -> None:
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth._parse_token_response({"refresh_token": "x"})


@pytest.mark.asyncio
async def test_exchange_code_calls_token_endpoint(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(url, data, *, timeout=15.0):
        captured["url"] = url
        captured["data"] = data
        return {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "scope": "gmail.readonly",
        }

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(google_oauth, "_client_secret", lambda: "csecret")
    monkeypatch.setattr(google_oauth, "_post", fake_post)

    tokens = await google_oauth.exchange_code("auth-code")
    assert captured["url"] == google_oauth._TOKEN_URL
    assert captured["data"]["code"] == "auth-code"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["client_id"] == "cid"
    assert captured["data"]["client_secret"] == "csecret"
    assert tokens.access_token == "at"


@pytest.mark.asyncio
async def test_refresh_uses_refresh_grant(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(url, data, *, timeout=15.0):
        captured["data"] = data
        return {"access_token": "new-at", "expires_in": 1800}

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(google_oauth, "_client_secret", lambda: "s")
    monkeypatch.setattr(google_oauth, "_post", fake_post)

    tokens = await google_oauth.refresh_access_token("rt-1")
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "rt-1"
    assert tokens.access_token == "new-at"


@pytest.mark.asyncio
async def test_fetch_user_email(monkeypatch) -> None:
    async def fake_get(url, *, token, timeout=15.0):
        assert token == "tok"
        return {"email": "alice@example.com", "verified_email": True}

    monkeypatch.setattr(google_oauth, "_get", fake_get)
    email = await google_oauth.fetch_user_email("tok")
    assert email == "alice@example.com"


@pytest.mark.asyncio
async def test_access_token_for_uses_stored_refresh(monkeypatch) -> None:
    monkeypatch.setattr(google_oauth, "load_refresh_token", lambda email: "stored-rt")

    seen: dict = {}

    async def fake_refresh(rt):
        seen["rt"] = rt
        return SimpleNamespace(
            access_token="fresh-at",
            refresh_token=None,
            expires_at=datetime.now(timezone.utc),
            scope="",
        )

    monkeypatch.setattr(google_oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(google_oauth, "store_refresh_token", lambda *a, **k: None)

    token = await google_oauth.access_token_for("alice@example.com")
    assert token == "fresh-at"
    assert seen["rt"] == "stored-rt"


@pytest.mark.asyncio
async def test_access_token_rotates_refresh_when_google_issues_new(monkeypatch) -> None:
    monkeypatch.setattr(google_oauth, "load_refresh_token", lambda email: "old-rt")

    rotated: dict = {}

    async def fake_refresh(rt):
        return SimpleNamespace(
            access_token="at",
            refresh_token="new-rt",
            expires_at=datetime.now(timezone.utc),
            scope="",
        )

    def fake_store(email, rt):
        rotated[email] = rt

    monkeypatch.setattr(google_oauth, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(google_oauth, "store_refresh_token", fake_store)

    await google_oauth.access_token_for("alice@example.com")
    assert rotated["alice@example.com"] == "new-rt"
