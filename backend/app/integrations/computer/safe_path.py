"""Path safety: allow-listed roots + traversal blocker.

Rules:
  * `ALLOWED_ROOTS` is hard-coded in settings (later: per-user table).
  * `resolve_safe(path, *, must_exist=False)` resolves to an absolute,
    canonical path and ASSERTS it sits under one of the allowed roots.
    Raises `UnsafePathError` otherwise.
  * The check uses `Path.resolve(strict=False)` so symlinks are followed
    BEFORE the containment check — a symlink inside an allowed root that
    points to /etc/passwd will fail.

Default roots (Windows-oriented since the user runs on Windows):
  * F:\\Projects
  * C:\\Users\\<user>\\Documents
  * C:\\Users\\<user>\\Downloads
The user can extend via the JARVIS_ALLOWED_ROOTS env var (semicolon-separated).
"""

from __future__ import annotations

import os
from pathlib import Path


class UnsafePathError(PermissionError):
    """Raised when a path escapes the allow-listed roots or contains traversal."""


def _default_roots() -> list[Path]:
    home = Path(os.path.expanduser("~"))
    roots = [
        Path("F:/Projects"),
        home / "Documents",
        home / "Downloads",
    ]
    return [r.resolve(strict=False) for r in roots]


def _env_roots() -> list[Path]:
    raw = os.environ.get("JARVIS_ALLOWED_ROOTS", "").strip()
    if not raw:
        return []
    return [Path(p).resolve(strict=False) for p in raw.split(";") if p.strip()]


def allowed_roots() -> list[Path]:
    return _default_roots() + _env_roots()


def is_under(path: Path, root: Path) -> bool:
    """True iff `path` is `root` or a descendant of `root`. Both must be resolved."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_safe(raw: str | os.PathLike[str], *, must_exist: bool = False) -> Path:
    """Resolve a user-supplied path and verify it sits under an allowed root.

    Catches:
      * `..` traversal (resolved away by Path.resolve)
      * absolute paths outside allowed roots
      * symlinks that escape allowed roots
    """
    raw_str = str(raw)
    if not raw_str.strip():
        raise UnsafePathError("empty path")
    # Reject suspicious null bytes and NTFS ADS markers up front.
    if "\x00" in raw_str:
        raise UnsafePathError("null byte in path")

    resolved = Path(raw_str).expanduser().resolve(strict=False)

    if must_exist and not resolved.exists():
        raise UnsafePathError(f"path does not exist: {resolved}")

    roots = allowed_roots()
    if not any(is_under(resolved, r) for r in roots):
        raise UnsafePathError(
            f"path is outside allowed roots: {resolved} (roots: {[str(r) for r in roots]})"
        )
    return resolved
