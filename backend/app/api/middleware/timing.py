"""Request timing middleware.

Adds an `X-Process-Time` response header (milliseconds) and logs requests
that take longer than `slow_threshold_ms`. Slow logs include the path and
method but never the query string or body — keeps log noise low while
making perf regressions visible.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("jarvis.perf")

DEFAULT_SLOW_MS = 1000


class TimingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, slow_threshold_ms: int = DEFAULT_SLOW_MS) -> None:
        super().__init__(app)
        self.slow_threshold_ms = slow_threshold_ms

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if response is not None:
                response.headers["X-Process-Time"] = str(elapsed_ms)
            if elapsed_ms >= self.slow_threshold_ms:
                logger.warning(
                    "slow_request method=%s path=%s elapsed_ms=%d status=%s",
                    request.method,
                    request.url.path,
                    elapsed_ms,
                    response.status_code if response is not None else "ERR",
                )
