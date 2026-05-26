"""Request timing middleware."""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.timing import TimingMiddleware


def _make_app(slow_ms: int = 1000) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TimingMiddleware, slow_threshold_ms=slow_ms)

    @app.get("/fast")
    async def fast():
        return {"ok": True}

    @app.get("/slow")
    async def slow():
        # Sleep just long enough to cross a very-low threshold.
        await asyncio.sleep(0.05)
        return {"ok": True}

    return app


def test_x_process_time_header_set_on_response() -> None:
    client = TestClient(_make_app())
    r = client.get("/fast")
    assert r.status_code == 200
    assert "x-process-time" in {k.lower() for k in r.headers}
    value = r.headers["x-process-time"]
    assert value.isdigit()
    assert int(value) >= 0


def test_slow_request_logged_when_over_threshold(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_make_app(slow_ms=1))  # 1ms threshold
    with caplog.at_level(logging.WARNING, logger="jarvis.perf"):
        client.get("/slow")
    assert any("slow_request" in r.getMessage() for r in caplog.records)


def test_fast_request_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_make_app(slow_ms=60_000))  # 60s — nothing reaches this
    with caplog.at_level(logging.WARNING, logger="jarvis.perf"):
        client.get("/fast")
    assert not any("slow_request" in r.getMessage() for r in caplog.records)
