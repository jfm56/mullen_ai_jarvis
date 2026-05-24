"""Google Calendar: pure-Python helpers (URL builder, time parser).

OAuth + live API calls are deferred to a `requires_google` marker.
"""

from __future__ import annotations

import pytest

from app.integrations import google_calendar as gc


def test_authorize_url_requires_client_id(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    with pytest.raises(gc.GoogleCalendarError):
        gc.authorize_url(state="abc")


def test_authorize_url_includes_state_and_scopes(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "fake-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT", "http://127.0.0.1:8000/auth/google/callback")
    url = gc.authorize_url(state="csrf-token-1234")
    assert "client_id=fake-client-id.apps.googleusercontent.com" in url
    assert "state=csrf-token-1234" in url
    assert "calendar.readonly" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_authorize_url_accepts_write_scope(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    url = gc.authorize_url(state="x", scopes=gc.SCOPES_WRITE)
    assert "calendar.events" in url


def test_parse_times_dateTime() -> None:
    raw = {
        "id": "abc",
        "start": {"dateTime": "2026-05-24T14:00:00+00:00"},
        "end": {"dateTime": "2026-05-24T15:00:00+00:00"},
    }
    start, end, all_day = gc._parse_times(raw)
    assert start.hour == 14
    assert end.hour == 15
    assert all_day is False


def test_parse_times_all_day() -> None:
    raw = {
        "id": "abc",
        "start": {"date": "2026-05-24"},
        "end": {"date": "2026-05-25"},
    }
    start, end, all_day = gc._parse_times(raw)
    assert all_day is True
    assert start.year == 2026 and start.month == 5 and start.day == 24


def test_parse_times_rejects_missing_start() -> None:
    with pytest.raises(gc.GoogleCalendarError):
        gc._parse_times({"id": "abc", "start": {}, "end": {}})
