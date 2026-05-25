"""Read-only file operations within allow-listed roots.

Search / list / read. No write, delete, rename, or move — those would
need explicit destructive-action approval at the agent layer, and we
don't expose them here in v1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.integrations.computer.safe_path import UnsafePathError, allowed_roots, resolve_safe


_MAX_RESULTS = 200
_MAX_READ_BYTES = 256 * 1024  # 256 KiB read cap; agent should ask for ranges for bigger


@dataclass
class FileEntry:
    path: str
    is_dir: bool
    size: int
    modified: float  # epoch seconds


def list_dir(raw: str) -> list[FileEntry]:
    p = resolve_safe(raw, must_exist=True)
    if not p.is_dir():
        raise UnsafePathError(f"not a directory: {p}")
    out: list[FileEntry] = []
    for child in sorted(p.iterdir()):
        try:
            st = child.stat()
        except OSError:
            continue
        out.append(
            FileEntry(
                path=str(child),
                is_dir=child.is_dir(),
                size=st.st_size,
                modified=st.st_mtime,
            )
        )
        if len(out) >= _MAX_RESULTS:
            break
    return out


def search(query: str, *, root: str | None = None, max_results: int = 50) -> list[FileEntry]:
    """Glob-style filename match. `query` is a glob like '**/*.csv'.

    If `root` is None, all allowed roots are searched. Returns at most
    `max_results` (capped at _MAX_RESULTS internally).
    """
    if not query or "\x00" in query:
        raise UnsafePathError("invalid query")
    cap = min(max_results, _MAX_RESULTS)

    roots: list[Path] = (
        [resolve_safe(root, must_exist=True)] if root else allowed_roots()
    )
    out: list[FileEntry] = []
    for r in roots:
        if not r.exists():
            continue
        for hit in r.glob(query):
            try:
                st = hit.stat()
            except OSError:
                continue
            out.append(
                FileEntry(
                    path=str(hit),
                    is_dir=hit.is_dir(),
                    size=st.st_size,
                    modified=st.st_mtime,
                )
            )
            if len(out) >= cap:
                return out
    return out


def read_text(raw: str) -> str:
    """Read a text file inside allowed roots. Capped at 256 KiB."""
    p = resolve_safe(raw, must_exist=True)
    if not p.is_file():
        raise UnsafePathError(f"not a file: {p}")
    with p.open("rb") as f:
        data = f.read(_MAX_READ_BYTES + 1)
    truncated = len(data) > _MAX_READ_BYTES
    text = data[:_MAX_READ_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += "\n\n[... truncated at 256 KiB ...]"
    return text
