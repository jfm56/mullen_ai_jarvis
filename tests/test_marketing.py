"""Marketing agent: calendar prompts, topic suggestions, draft gating."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.marketing.agent import MarketingAgent, _CalendarSnapshot
from app.db.models import SocialPlatform, Vertical
from app.integrations import ollama
from app.security.permissions import ActionClass, Decision, PermissionLevel


def _snap(drafts: int = 0, scheduled: int = 0, published_7d: int = 0,
          by_platform=None, by_vertical=None, upcoming=()) -> _CalendarSnapshot:
    return _CalendarSnapshot(
        today=datetime(2026, 5, 25, tzinfo=timezone.utc),
        drafts=drafts,
        scheduled=scheduled,
        published_last_7d=published_7d,
        by_platform=by_platform or {},
        by_vertical=by_vertical or {},
        upcoming=list(upcoming),
    )


def test_prompt_empty_calendar() -> None:
    prompt = MarketingAgent._build_prompt("what's on deck?", _snap())
    assert "drafts: 0" in prompt
    assert "scheduled: 0" in prompt
    assert "User asked: what's on deck?" in prompt


def test_prompt_lists_breakdowns_and_upcoming() -> None:
    upcoming = [
        SimpleNamespace(
            scheduled_for=datetime(2026, 5, 26, 10, tzinfo=timezone.utc),
            platform=SimpleNamespace(value="linkedin"),
            vertical=SimpleNamespace(value="ems"),
            title="response time analytics",
            body_text="",
        ),
    ]
    prompt = MarketingAgent._build_prompt(
        "what's hot?",
        _snap(drafts=3, scheduled=1, published_7d=2,
              by_platform={"linkedin": 3, "x": 1},
              by_vertical={"ems": 2, "drone": 2},
              upcoming=upcoming),
    )
    assert "drafts: 3" in prompt
    assert "scheduled: 1" in prompt
    assert "published in last 7 days: 2" in prompt
    assert "linkedin=3" in prompt
    assert "[linkedin/ems] response time analytics" in prompt


def test_prompt_substitutes_default_input() -> None:
    prompt = MarketingAgent._build_prompt("  ", _snap())
    assert "User asked: What does the content calendar look like?" in prompt


def test_fallback_text_is_deterministic() -> None:
    text = MarketingAgent._fallback_text(_snap(drafts=2, scheduled=1, published_7d=3))
    assert text == "2 draft(s), 1 scheduled, 3 published in last 7 days."


def test_suggest_topics_returns_seeds_per_vertical() -> None:
    ems = MarketingAgent.suggest_topics(Vertical.ems, count=3)
    assert len(ems) == 3
    assert any("response-time" in t.lower() or "response time" in t.lower() for t in ems)

    drone = MarketingAgent.suggest_topics(Vertical.drone)
    assert any("bvlos" in t.lower() or "part 107" in t.lower() for t in drone)

    other = MarketingAgent.suggest_topics(Vertical.other)
    assert len(other) >= 1


def test_post_prompt_contains_platform_and_vertical_voice() -> None:
    p = MarketingAgent._post_prompt(
        SocialPlatform.x,
        Vertical.ems,
        "EMS triage analytics",
        "lead with a stat",
    )
    assert "250-280 chars" in p
    assert "field-operations" in p
    assert "EMS triage analytics" in p
    assert "lead with a stat" in p
    assert "no banned words" in p.lower()


@pytest.mark.asyncio
async def test_handle_uses_fallback_when_llm_down(monkeypatch) -> None:
    agent = MarketingAgent()

    async def fake_collect(self, ctx):  # noqa: ARG001
        return _snap(drafts=2, scheduled=0, published_7d=1)

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(MarketingAgent, "_collect_calendar", fake_collect)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.draft_only,
        request_id="r",
        input_text="",
        metadata={},
    )
    result = await agent.handle(ctx)
    assert "2 draft(s)" in result.text
    assert "LLM unavailable" in result.text
    assert result.metadata["drafts"] == 2


@pytest.mark.asyncio
async def test_draft_post_routes_through_approval_gate_even_at_admin(monkeypatch) -> None:
    """Critical: publishing a social post requires approval even at admin level."""
    agent = MarketingAgent()
    captured: dict = {}

    async def fake_generate(*args, **kwargs):
        return SimpleNamespace(text="draft body text", model="x", raw={})

    class FakeSession:
        def add(self, *_): pass
        async def commit(self): pass
        async def refresh(self, obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

    class FakeSessionMaker:
        def __call__(self): return self
        async def __aenter__(self): return FakeSession()
        async def __aexit__(self, *a): return False

    async def fake_propose(self, ctx, action, **kwargs):
        captured["action"] = action
        captured["preview"] = kwargs.get("preview", "")
        return SimpleNamespace(decision=Decision.require_approval, approval=SimpleNamespace(id=uuid.uuid4()))

    monkeypatch.setattr(ollama, "generate", fake_generate)
    monkeypatch.setattr("app.agents.marketing.agent.get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(MarketingAgent, "propose", fake_propose)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.admin,
        request_id="r",
        input_text="",
        metadata={},
    )
    post, outcome = await agent.draft_post(
        ctx, platform=SocialPlatform.linkedin, vertical=Vertical.drone,
        topic="BVLOS waivers",
    )
    assert captured["action"].action_class is ActionClass.action_external_send
    assert captured["action"].name == "social.publish"
    assert "linkedin" in captured["action"].target_summary
    assert "BVLOS" in captured["action"].target_summary
    assert outcome.decision is Decision.require_approval


@pytest.mark.asyncio
async def test_draft_post_falls_back_when_llm_down(monkeypatch) -> None:
    agent = MarketingAgent()

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    class FakeSession:
        def add(self, *_): pass
        async def commit(self): pass
        async def refresh(self, obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

    class FakeSessionMaker:
        def __call__(self): return self
        async def __aenter__(self): return FakeSession()
        async def __aexit__(self, *a): return False

    async def fake_propose(self, ctx, action, **kwargs):
        return SimpleNamespace(decision=Decision.require_approval, approval=SimpleNamespace(id=uuid.uuid4()))

    monkeypatch.setattr(ollama, "generate", fake_generate)
    monkeypatch.setattr("app.agents.marketing.agent.get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(MarketingAgent, "propose", fake_propose)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.draft_only,
        request_id="r",
        input_text="",
        metadata={},
    )
    post, _ = await agent.draft_post(
        ctx, platform=SocialPlatform.linkedin, vertical=Vertical.ems, topic="EMS metrics",
    )
    assert "Could not draft via LLM" in post.body_text
