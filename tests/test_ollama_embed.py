"""Ollama embeddings wrapper."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.integrations import ollama


@pytest.mark.asyncio
async def test_embed_builds_payload_and_returns_vector(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_call(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        seen["url"] = url
        seen["payload"] = payload
        return {"embedding": [0.1, 0.2, 0.3]}

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    result = await ollama.embed("the quick brown fox", model="nomic-embed-text")
    assert result.vector == [0.1, 0.2, 0.3]
    assert result.model == "nomic-embed-text"
    assert seen["url"].endswith("/api/embeddings")
    assert seen["payload"]["prompt"] == "the quick brown fox"


@pytest.mark.asyncio
async def test_embed_wraps_http_error(monkeypatch) -> None:
    async def fake_call(url, payload, *, timeout):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    with pytest.raises(ollama.OllamaError):
        await ollama.embed("hi")


@pytest.mark.asyncio
async def test_embed_rejects_empty_vector(monkeypatch) -> None:
    async def fake_call(url, payload, *, timeout):
        return {"embedding": []}

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    with pytest.raises(ollama.OllamaError):
        await ollama.embed("hi")


@pytest.mark.asyncio
async def test_embed_rejects_missing_field(monkeypatch) -> None:
    async def fake_call(url, payload, *, timeout):
        return {"oops": "wrong"}

    monkeypatch.setattr(ollama, "_call_api", fake_call)
    with pytest.raises(ollama.OllamaError):
        await ollama.embed("hi")
