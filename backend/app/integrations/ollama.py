"""Local LLM via Ollama.

All agents call here rather than importing the `ollama` SDK directly.
This is the single place to add sensitive-data redaction, rate limiting,
prompt logging, or to swap providers.

Tests patch `_call_api` to avoid hitting a live Ollama server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings


class OllamaError(RuntimeError):
    pass


@dataclass
class GenerateResult:
    text: str
    model: str
    raw: dict[str, Any]


@dataclass
class EmbedResult:
    vector: list[float]
    model: str


async def _call_api(
    url: str, payload: dict[str, Any], *, timeout: float
) -> dict[str, Any]:
    """Single HTTP call. Patched in tests."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def generate(
    prompt: str,
    *,
    model: str | None = None,
    system: str | None = None,
    options: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> GenerateResult:
    """Synchronous-style single-shot generation against Ollama.

    Streaming + chat-history calls land later (Phase 4+ for the Email
    Assistant). The Personal Assistant only needs single-turn for now.
    """
    settings = get_settings()
    chosen_model = model or settings.ollama_default_model
    payload: dict[str, Any] = {
        "model": chosen_model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    url = settings.ollama_host.rstrip("/") + "/api/generate"
    try:
        data = await _call_api(url, payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise OllamaError(f"ollama call failed: {exc}") from exc

    if "response" not in data:
        raise OllamaError(f"unexpected ollama response shape: keys={list(data.keys())}")

    return GenerateResult(text=data["response"], model=chosen_model, raw=data)


async def embed(
    text: str,
    *,
    model: str | None = None,
    timeout: float = 30.0,
) -> EmbedResult:
    """Compute an embedding for `text` via Ollama's /api/embeddings.

    Returns a vector whose dimension matches the chosen model. The
    application's pgvector column has a fixed dimension (settings.embedding_dim)
    — callers that mix models must validate the returned length matches.
    """
    settings = get_settings()
    chosen_model = model or settings.ollama_embedding_model
    payload = {"model": chosen_model, "prompt": text}
    url = settings.ollama_host.rstrip("/") + "/api/embeddings"

    try:
        data = await _call_api(url, payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise OllamaError(f"ollama embed failed: {exc}") from exc

    vector = data.get("embedding")
    if not isinstance(vector, list) or not vector:
        raise OllamaError(f"unexpected embeddings shape: keys={list(data.keys())}")
    return EmbedResult(vector=vector, model=chosen_model)
