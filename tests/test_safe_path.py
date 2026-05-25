"""Path safety: traversal blocker + allow-listed roots.

The most safety-critical primitive in the project. If this drifts,
the Computer Control agent can wander outside its sandbox.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.integrations.computer import safe_path


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    """Restrict allowed roots to a tmp_path for the duration of the test."""
    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(tmp_path))
    # Also wipe the defaults so HOME/Projects don't interfere.
    monkeypatch.setattr(safe_path, "_default_roots", lambda: [])
    return tmp_path


def test_traversal_via_dot_dot_blocked(sandbox: Path) -> None:
    bad = str(sandbox / ".." / "etc" / "passwd")
    with pytest.raises(safe_path.UnsafePathError):
        safe_path.resolve_safe(bad)


def test_absolute_path_outside_roots_blocked(sandbox: Path) -> None:
    with pytest.raises(safe_path.UnsafePathError):
        safe_path.resolve_safe("C:/Windows/System32/cmd.exe" if os.name == "nt" else "/etc/passwd")


def test_path_inside_sandbox_resolves(sandbox: Path) -> None:
    target = sandbox / "subdir" / "file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("ok", encoding="utf-8")
    resolved = safe_path.resolve_safe(target, must_exist=True)
    assert resolved == target.resolve()


def test_empty_path_blocked(sandbox: Path) -> None:
    with pytest.raises(safe_path.UnsafePathError):
        safe_path.resolve_safe("   ")


def test_null_byte_blocked(sandbox: Path) -> None:
    with pytest.raises(safe_path.UnsafePathError):
        safe_path.resolve_safe(str(sandbox / "foo\x00bar"))


def test_must_exist_flag_rejects_missing(sandbox: Path) -> None:
    target = sandbox / "does-not-exist.txt"
    with pytest.raises(safe_path.UnsafePathError):
        safe_path.resolve_safe(target, must_exist=True)


def test_must_exist_false_allows_missing_inside_root(sandbox: Path) -> None:
    target = sandbox / "will-be-created.txt"
    resolved = safe_path.resolve_safe(target)  # must_exist=False default
    assert resolved == target.resolve()


def test_is_under_self_is_true(sandbox: Path) -> None:
    r = sandbox.resolve()
    assert safe_path.is_under(r, r) is True


def test_is_under_unrelated_is_false(sandbox: Path, tmp_path_factory) -> None:
    other = tmp_path_factory.mktemp("other").resolve()
    assert safe_path.is_under(other, sandbox.resolve()) is False
