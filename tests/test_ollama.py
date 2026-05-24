"""Ollama wrapper: payload shape, error handling.

The real HTTP call is patched — no Ollama server required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.integrations import ollama


@pytest.mark.asyncio
async def test_generate_builds_payload_and_returns_text(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_call(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        seen["url"] = url
        seen["payload"] = payload
        seen["timeout"] = timeout
        return {"response": "hello world", "model": payload["model"], "done": True}

    monkeypatch.setattr(ollama, "_call_api", fake_call)

    result = await ollama.generate(
        "say hi", model="llama3.1:8b", system="be brief", options={"temperature": 0.0}
    )

    assert result.text == "hello world"
    assert result.model == "llama3.1:8b"
    assert seen["url"].endswith("/api/generate")
    assert seen["payload"]["model"] == "llama3.1:8b"
    assert seen["payload"]["prompt"] == "say hi"
    assert seen["payload"]["system"] == "be brief"
    assert seen["payload"]["stream"] is False
    assert seen["payload"]["options"] == {"temperature": 0.0}


@pytest.mark.asyncio
async def test_generate_uses_default_model(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_call(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        captured["model"] = payload["model"]
        return {"response": "ok"}

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    await ollama.generate("hi")
    assert captured["model"]  # whatever the configured default is


@pytest.mark.asyncio
async def test_generate_wraps_http_error(monkeypatch) -> None:
    async def fake_call(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    with pytest.raises(ollama.OllamaError) as exc:
        await ollama.generate("hi")
    assert "connection refused" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_rejects_unexpected_shape(monkeypatch) -> None:
    async def fake_call(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        return {"oops": "wrong shape"}

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    with pytest.raises(ollama.OllamaError):
        await ollama.generate("hi")
