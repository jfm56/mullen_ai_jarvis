"""Gmail integration: URL builder + message parser."""

from __future__ import annotations

import base64

import pytest

from app.integrations import gmail


def test_authorize_url_requires_client_id(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    with pytest.raises(gmail.GmailError):
        gmail.authorize_url(state="x")


def test_authorize_url_read_only_by_default(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    url = gmail.authorize_url(state="csrf-1")
    assert "gmail.readonly" in url
    assert "gmail.send" not in url


def test_authorize_url_with_send_scope(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    url = gmail.authorize_url(state="csrf-1", include_send=True)
    assert "gmail.readonly" in url
    assert "gmail.send" in url


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).rstrip(b"=").decode()


def test_parse_message_extracts_headers_and_body() -> None:
    raw = {
        "id": "msg-1",
        "threadId": "thr-1",
        "labelIds": ["INBOX", "IMPORTANT"],
        "snippet": "hi there",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "jim@mullen.com"},
                {"name": "Subject", "value": "lunch?"},
                {"name": "Date", "value": "Sat, 24 May 2026 14:00:00 +0000"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("hey jim,\nlunch?")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>hey</p>")}},
            ],
        },
    }
    parsed = gmail.parse_message(raw)
    assert parsed["external_id"] == "msg-1"
    assert parsed["thread_id"] == "thr-1"
    assert parsed["from_addr"] == "Alice <alice@example.com>"
    assert parsed["subject"] == "lunch?"
    assert "hey jim" in parsed["body_text"]
    assert "INBOX" in parsed["labels"]
    assert parsed["received_at"].year == 2026


def test_parse_message_handles_missing_date_gracefully() -> None:
    raw = {
        "id": "m2",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "x"}],
            "body": {"data": _b64("body")},
        },
    }
    parsed = gmail.parse_message(raw)
    assert parsed["received_at"] is not None
    assert parsed["body_text"] == "body"


def test_parse_message_walks_nested_parts() -> None:
    raw = {
        "id": "m3",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("nested text")}},
                    ],
                }
            ],
        },
    }
    parsed = gmail.parse_message(raw)
    assert parsed["body_text"] == "nested text"
