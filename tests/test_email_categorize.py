"""Email categorizer: LLM happy path + fallbacks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.email_assistant.categorize import categorize
from app.db.models import EmailCategory
from app.integrations import ollama


@pytest.mark.asyncio
async def test_categorize_uses_llm_when_valid(monkeypatch) -> None:
    async def fake_generate(prompt, *, system=None, model=None, **kwargs):
        return SimpleNamespace(text="lead_inquiry\n", model="x", raw={})

    monkeypatch.setattr(ollama, "generate", fake_generate)
    r = await categorize(subject="Need a quote", body_text="...", from_addr="x@y.com")
    assert r.category is EmailCategory.lead_inquiry
    assert r.via == "llm"
    assert r.confidence == 1.0


@pytest.mark.asyncio
async def test_categorize_falls_back_when_llm_returns_garbage(monkeypatch) -> None:
    async def fake_generate(prompt, *, system=None, model=None, **kwargs):
        return SimpleNamespace(text="I think this is probably... hmm", model="x", raw={})

    monkeypatch.setattr(ollama, "generate", fake_generate)
    r = await categorize(
        subject="weekly digest from substack",
        body_text="unsubscribe at the bottom",
        from_addr="news@substack.com",
    )
    assert r.category is EmailCategory.newsletter
    assert r.via == "fallback"


@pytest.mark.asyncio
async def test_categorize_falls_back_when_llm_down(monkeypatch) -> None:
    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ollama, "generate", fake_generate)
    r = await categorize(
        subject="Re: proposal for EMS analytics engagement",
        body_text="Interested in services",
        from_addr="cto@ems-co.com",
    )
    assert r.category is EmailCategory.lead_inquiry
    assert r.via == "fallback"


@pytest.mark.asyncio
async def test_fallback_internal_for_mullen_sender(monkeypatch) -> None:
    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ollama, "generate", fake_generate)
    r = await categorize(
        subject="standup notes",
        body_text="see attached",
        from_addr="bob@mullenanalytics.com",
    )
    assert r.category is EmailCategory.internal


@pytest.mark.asyncio
async def test_fallback_fyi_for_unmatched(monkeypatch) -> None:
    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ollama, "generate", fake_generate)
    r = await categorize(
        subject="thank you",
        body_text="appreciate the chat",
        from_addr="x@y.com",
    )
    assert r.category is EmailCategory.fyi


@pytest.mark.asyncio
async def test_categorize_strips_explanatory_garbage_to_first_token(monkeypatch) -> None:
    async def fake_generate(prompt, *, system=None, model=None, **kwargs):
        return SimpleNamespace(text="urgent — needs reply by EOD", model="x", raw={})

    monkeypatch.setattr(ollama, "generate", fake_generate)
    r = await categorize(subject="x", body_text="", from_addr="")
    assert r.category is EmailCategory.urgent
    assert r.via == "llm"
