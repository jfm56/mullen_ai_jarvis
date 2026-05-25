"""sha256 helpers for script integrity checks.

Used at two moments:
  1. When the user registers an AllowedScript — the current file hash is
     stored as `expected_hash`.
  2. Immediately before each execution — `verify_hash` is called; if the
     file on disk has changed (compromise, tampering, accidental edit),
     the run is BLOCKED and a `blocked` row is written to the action log.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class HashMismatchError(PermissionError):
    """Raised when actual file hash does not match expected."""


def sha256_of(path: Path) -> str:
    """Compute lowercase hex sha256 of file at `path`. Streams large files."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_hash(path: Path, expected_hex: str) -> None:
    """Raise HashMismatchError if `path` does not hash to `expected_hex`.

    Comparison is constant-time-ish on the hex string. Both sides are
    lowercased before compare.
    """
    if not expected_hex or len(expected_hex) != 64:
        raise HashMismatchError(f"expected hash is not a valid sha256 hex: {expected_hex!r}")
    actual = sha256_of(path)
    if not _constant_eq(actual, expected_hex.lower()):
        raise HashMismatchError(
            f"hash mismatch for {path}: expected {expected_hex[:12]}..., got {actual[:12]}..."
        )


def _constant_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0
