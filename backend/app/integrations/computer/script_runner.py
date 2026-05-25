"""Run a script from an AllowedScript row.

Hash is RE-VERIFIED immediately before each execution. If a file has
changed since the row was created — whether by tampering, by an editor,
or by an accidental edit — the run is BLOCKED. The agent records a
`blocked` row in `computer_action_log` with the reason.

Interpreter handling:
  * If `interpreter` is empty, the script path itself is the executable
    (e.g., a .exe or a shebang'd Unix script).
  * If `interpreter` is set, it's resolved via shutil.which and used as
    the executable, with the script path as the first arg.
"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from app.db.models import AllowedScript
from app.integrations.computer import file_hash, safe_path, subprocess_safe


class ScriptRunError(RuntimeError):
    pass


def _split_args(template: str, user_args: str | None) -> list[str]:
    args: list[str] = []
    if template.strip():
        args.extend(shlex.split(template))
    if user_args and user_args.strip():
        args.extend(shlex.split(user_args))
    return args


async def run(script: AllowedScript, *, user_args: str | None = None,
              timeout: float = 60.0) -> subprocess_safe.RunResult:
    p = Path(script.path)
    try:
        resolved = safe_path.resolve_safe(p, must_exist=True)
    except safe_path.UnsafePathError as exc:
        raise ScriptRunError(f"script path is unsafe: {exc}") from exc

    # Hash is always required for scripts.
    try:
        file_hash.verify_hash(resolved, script.sha256_hash)
    except file_hash.HashMismatchError as exc:
        raise ScriptRunError(f"hash mismatch — refusing to run: {exc}") from exc

    user_arg_list = _split_args(script.args_template, user_args)

    if script.interpreter.strip():
        interp = shutil.which(script.interpreter)
        if not interp:
            raise ScriptRunError(f"interpreter not found on PATH: {script.interpreter!r}")
        executable = interp
        args = [str(resolved), *user_arg_list]
    else:
        executable = str(resolved)
        args = user_arg_list

    try:
        return await subprocess_safe.run(executable, args, timeout=timeout)
    except subprocess_safe.UnsafeArgError as exc:
        raise ScriptRunError(f"unsafe args: {exc}") from exc
