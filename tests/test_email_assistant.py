"""Email Assistant agent: enrichment + draft approval gating."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.email_assistant.agent import EmailAssistantAgent, InboxSummary
from app.db.models import EmailCategory, EmailDirection
from app.integrations import ollama


def _fake_email(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "from_addr": "alice@example.com",
        "to_addrs": "jim@mullen.com",
        "cc_addrs": "",
        "subject": "Re: project",
        "body_text": "Hey Jim, can you confirm the kickoff date?",
        "received_at": datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
        "labels": [],
        "category": EmailCategory.unclassified,
        "urgency_score": 0.0,
        "is_scam": False,
        "scam_score": 0.0,
        "scam_signals": [],
        "read": False,
        "archived": False,
        "domain": "personal",
        "direction": EmailDirection.inbound,
        "synced_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_summary_prompt_lists_categories_and_flags() -> None:
    s = InboxSummary(
        total=12,
        by_category={"urgent": 2, "fyi": 8, "newsletter": 2},
        flagged_scam=1,
        waiting_on_user=3,
        overdue_unread_days=4,
    )
    prompt = EmailAssistantAgent._build_prompt("what should I focus on?", s)
    assert "12 messages" in prompt
    assert "urgent=2" in prompt
    assert "Waiting on you: 3" in prompt
    assert "Flagged as suspicious: 1" in prompt
    assert "Oldest unread (non-scam): 4 days" in prompt
    assert "User asked: what should I focus on?" in prompt


def test_summary_prompt_substitutes_default_input() -> None:
    s = InboxSummary(total=0, by_category={}, flagged_scam=0, waiting_on_user=0, overdue_unread_days=0)
    prompt = EmailAssistantAgent._build_prompt("  ", s)
    assert "User asked: Summarize my inbox." in prompt


def test_fallback_text_is_deterministic() -> None:
    s = InboxSummary(
        total=5, by_category={}, flagged_scam=1, waiting_on_user=2, overdue_unread_days=0
    )
    text = EmailAssistantAgent._fallback_text(s)
    assert text.startswith("5 emails in last 7 days")
    assert "2 waiting on you" in text
    assert "1 flagged as scam" in text


@pytest.mark.asyncio
async def test_enrich_flags_obvious_scam_and_skips_categorizer(monkeypatch) -> None:
    agent = EmailAssistantAgent()
    email = _fake_email(
        from_addr="security@paypa1.com",
        subject="Verify your account immediately",
        body_text="Click here to verify password and confirm bank account details right away",
    )

    called = {"categorize": False}

    async def fake_categorize(**kwargs):
        called["categorize"] = True
        return SimpleNamespace(category=EmailCategory.fyi, confidence=1.0, via="llm")

    monkeypatch.setattr("app.agents.email_assistant.agent.categorize", fake_categorize)

    await agent.enrich(email)
    assert email.is_scam is True
    assert email.scam_score >= 0.6
    assert email.category is EmailCategory.suspicious
    assert called["categorize"] is False  # short-circuited


@pytest.mark.asyncio
async def test_enrich_categorizes_normal_email(monkeypatch) -> None:
    agent = EmailAssistantAgent()
    email = _fake_email()

    async def fake_categorize(**kwargs):
        return SimpleNamespace(category=EmailCategory.waiting_on_me, confidence=1.0, via="llm")

    monkeypatch.setattr("app.agents.email_assistant.agent.categorize", fake_categorize)
    await agent.enrich(email)
    assert email.is_scam is False
    assert email.category is EmailCategory.waiting_on_me


@pytest.mark.asyncio
async def test_handle_uses_fallback_when_llm_down(monkeypatch) -> None:
    agent = EmailAssistantAgent()

    async def fake_summarize(self, ctx):  # noqa: ARG001
        return InboxSummary(
            total=3, by_category={"fyi": 3}, flagged_scam=0,
            waiting_on_user=1, overdue_unread_days=0,
        )

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(EmailAssistantAgent, "_summarize_inbox", fake_summarize)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    from app.agents.base import AgentContext
    from app.security.permissions import PermissionLevel

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="personal",
        permission_level=PermissionLevel.draft_only,
        request_id="r",
        input_text="how bad is it?",
        metadata={},
    )
    result = await agent.handle(ctx)
    assert "3 emails in last 7 days" in result.text
    assert "LLM unavailable" in result.text
    assert result.metadata["total"] == 3
    assert result.metadata["waiting_on_user"] == 1
