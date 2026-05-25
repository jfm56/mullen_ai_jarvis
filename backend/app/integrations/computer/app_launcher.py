"""Launch an application from an AllowedApp row.

The agent NEVER passes arbitrary executable strings here — it must
load an AllowedApp from the DB and hand it over. This module:
  * verifies the path still resolves under an allowed root
  * (optionally) verifies the executable's sha256 if hash_required
  * validates and splits args
  * runs through the safe subprocess wrapper
"""

from __future__ import annotations

import shlex
from pathlib import Path

from app.db.models import AllowedApp
from app.integrations.computer import file_hash, safe_path, subprocess_safe


class AppLaunchError(RuntimeError):
    pass


def _split_args(template: str, user_args: str | None) -> list[str]:
    args: list[str] = []
    if template.strip():
        args.extend(shlex.split(template))
    if user_args and user_args.strip():
        args.extend(shlex.split(user_args))
    return args


async def launch(app: AllowedApp, *, user_args: str | None = None,
                 timeout: float = 30.0) -> subprocess_safe.RunResult:
    p = Path(app.path)
    try:
        resolved = safe_path.resolve_safe(p, must_exist=True)
    except safe_path.UnsafePathError as exc:
        raise AppLaunchError(f"app path is unsafe: {exc}") from exc

    if app.hash_required:
        if not app.expected_hash:
            raise AppLaunchError(
                f"app {app.name!r} requires hash verification but no expected hash is set"
            )
        try:
            file_hash.verify_hash(resolved, app.expected_hash)
        except file_hash.HashMismatchError as exc:
            raise AppLaunchError(f"app hash mismatch — refusing to launch: {exc}") from exc

    args = _split_args(app.args_template, user_args)
    try:
        return await subprocess_safe.run(str(resolved), args, timeout=timeout)
    except subprocess_safe.UnsafeArgError as exc:
        raise AppLaunchError(f"unsafe args: {exc}") from exc
