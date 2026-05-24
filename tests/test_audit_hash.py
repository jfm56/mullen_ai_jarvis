"""Audit log payload hashing (no DB required)."""

from __future__ import annotations

from app.security.audit import hash_payload


def test_hash_is_stable_and_short() -> None:
    h = hash_payload({"foo": "bar"})
    assert len(h) == 16
    assert hash_payload({"foo": "bar"}) == h


def test_hash_distinguishes_inputs() -> None:
    assert hash_payload({"a": 1}) != hash_payload({"a": 2})


def test_hash_does_not_leak_payload() -> None:
    secret = "sk-this-is-a-fake-api-key-1234567890"
    h = hash_payload({"api_key": secret})
    assert secret not in h
