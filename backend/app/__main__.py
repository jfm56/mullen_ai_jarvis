"""Console entrypoint:  python -m app

Why this exists instead of `uvicorn app.main:app`:

On Windows, psycopg's async driver REQUIRES a SelectorEventLoop, but the bare
`uvicorn` CLI builds its event loop (a ProactorEventLoop — Python's Windows
default) BEFORE it imports the app, so the policy set inside app.main lands too
late and every DB query fails with:

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' ...

Setting the policy here — before uvicorn.run() calls asyncio.run() — fixes it.
`loop="none"` tells uvicorn not to override the policy we just set (its
"asyncio"/"auto" setups force the ProactorEventLoop back on Windows). On other
platforms we keep "auto" so uvloop is still used when available.

Run:  python -m app
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402  (must come after the policy set)

from app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        # On Windows, "none" prevents uvicorn from re-forcing the Proactor loop;
        # elsewhere "auto" lets it pick uvloop.
        loop="none" if sys.platform == "win32" else "auto",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
