"""Safe subprocess wrapper.

Rules enforced here (not just at the agent layer, so a future bug in
an agent can't bypass them):

  * `shell=True` is forbidden — never invoke through a shell.
  * `executable` and `args` must be a list of already-validated strings;
    no string interpolation, no f-strings building command lines.
  * Each arg is checked for `..`, NUL bytes, and pipe/redirect characters.
  * stdout + stderr are captured (truncated to 4096 bytes) and returned.
  * A `timeout` is mandatory; default 30s; the caller can extend.

Returns a `RunResult` dataclass — never raises on non-zero exit; the
agent decides what to do with a failed return code.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


class UnsafeArgError(ValueError):
    pass


_DENY_ARG_CHARS = re.compile(r"[\x00|&;`$<>]")


def validate_args(args: list[str]) -> list[str]:
    """Validate every arg. Returns the same list on success; raises otherwise."""
    out: list[str] = []
    for i, a in enumerate(args):
        if not isinstance(a, str):
            raise UnsafeArgError(f"arg {i} is not a string: {type(a).__name__}")
        if "\x00" in a:
            raise UnsafeArgError(f"arg {i} contains null byte")
        if _DENY_ARG_CHARS.search(a):
            raise UnsafeArgError(f"arg {i} contains denied shell metacharacter: {a!r}")
        if ".." in a.replace("\\..\\", "/../").split("/"):
            raise UnsafeArgError(f"arg {i} contains path traversal")
        out.append(a)
    return out


@dataclass
class RunResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool


_OUTPUT_LIMIT = 4096


async def run(executable: str, args: list[str], *, timeout: float = 30.0,
              cwd: str | None = None, env: dict[str, str] | None = None) -> RunResult:
    """Run `executable` with `args`. Captures and truncates output.

    `executable` and each `args` element are validated. `shell=True` is
    not even a parameter here — there's no way to ask for it.
    """
    if not executable or not isinstance(executable, str):
        raise UnsafeArgError("executable must be a non-empty string")
    validate_args([executable, *args])

    proc = await asyncio.create_subprocess_exec(
        executable,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout_b, stderr_b = b"", b"(timed out)"
        timed_out = True

    stdout = stdout_b.decode("utf-8", errors="replace")[:_OUTPUT_LIMIT]
    stderr = stderr_b.decode("utf-8", errors="replace")[:_OUTPUT_LIMIT]
    return RunResult(
        return_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )
