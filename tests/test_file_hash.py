"""sha256 helpers + verify-before-execute."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.integrations.computer import file_hash


def test_sha256_of_known_content(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    # sha256("hello") known constant
    assert file_hash.sha256_of(f) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_verify_hash_match_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "ok.txt"
    f.write_text("script body", encoding="utf-8")
    expected = file_hash.sha256_of(f)
    file_hash.verify_hash(f, expected)  # should not raise


def test_verify_hash_mismatch_raises(tmp_path: Path) -> None:
    f = tmp_path / "ok.txt"
    f.write_text("original", encoding="utf-8")
    original = file_hash.sha256_of(f)
    # Tamper with the file.
    f.write_text("TAMPERED", encoding="utf-8")
    with pytest.raises(file_hash.HashMismatchError):
        file_hash.verify_hash(f, original)


def test_verify_hash_rejects_invalid_expected(tmp_path: Path) -> None:
    f = tmp_path / "ok.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(file_hash.HashMismatchError):
        file_hash.verify_hash(f, "not-a-hash")
    with pytest.raises(file_hash.HashMismatchError):
        file_hash.verify_hash(f, "")


def test_verify_hash_is_case_insensitive_on_expected(tmp_path: Path) -> None:
    f = tmp_path / "ok.txt"
    f.write_text("x", encoding="utf-8")
    expected = file_hash.sha256_of(f).upper()  # uppercase hex
    file_hash.verify_hash(f, expected)  # should still match
