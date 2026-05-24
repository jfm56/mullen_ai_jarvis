"""Local LLM via Ollama.

Default model from settings. All agents call here rather than the
ollama SDK directly so we can swap providers and add sensitive-data
checks in one place.
"""

from __future__ import annotations

from app.config import get_settings


async def generate(prompt: str, *, model: str | None = None, system: str | None = None) -> str:
    """Local LLM generation. Phase 2 implementation."""
    _ = model or get_settings().ollama_default_model
    raise NotImplementedError("integrations.ollama.generate — implement in Phase 2")
