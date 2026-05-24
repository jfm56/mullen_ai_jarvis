"""Password hashing + JWT token tests (no DB required)."""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi import HTTPException

from app.security.auth import (
    decode_token,
    hash_password,
    issue_token,
    needs_rehash,
    verify_password,
)


def test_hash_and_verify_roundtrip() -> None:
    pw = "correct horse battery staple"
    hashed = hash_password(pw)
    assert hashed != pw
    assert hashed.startswith("$argon2")
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_handles_garbage_hash() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


def test_needs_rehash_for_valid_current_hash_is_false() -> None:
    # A freshly produced hash should not need a rehash unless argon2 params changed.
    assert needs_rehash(hash_password("x")) is False


def test_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = issue_token(user_id)
    assert decode_token(token) == user_id


def test_token_rejects_tampered_signature() -> None:
    token = issue_token(uuid.uuid4())
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    with pytest.raises(HTTPException) as exc:
        decode_token(tampered)
    assert exc.value.status_code == 401


def test_token_rejects_expired() -> None:
    token = issue_token(uuid.uuid4(), ttl_min=0)
    # ttl_min=0 → exp == iat; give clock a moment so exp is strictly past.
    time.sleep(1.1)
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401
