"""Lead Generation: scoring, follow-up cadence, outreach gating."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.lead_generation.agent import (
    LeadGenerationAgent,
    _PipelineSnapshot,
    _CADENCE_DAYS,
)
from app.db.models import LeadSource, LeadStatus, OutreachChannel, Vertical
from app.integrations import ollama
from app.security.permissions import ActionClass, Decision, PermissionLevel


def _lead(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        name="",
        company="",
        role="",
        email="",
        phone="",
        vertical=Vertical.other,
        source=LeadSource.manual,
        status=LeadStatus.researched,
        score=0,
        notes="",
        last_contacted_at=None,
        next_followup_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---- scoring ---------------------------------------------------------------


def test_score_empty_lead_is_zero() -> None:
    assert LeadGenerationAgent.score_lead(_lead()) == 0


def test_score_ideal_target_vertical_lead_high() -> None:
    L = _lead(
        email="alice@township-ems.gov",
        company="Township EMS",
        role="Operations Director",
        vertical=Vertical.ems,
        source=LeadSource.referral,
        status=LeadStatus.contacted,
        notes="x" * 250,
    )
    score = LeadGenerationAgent.score_lead(L)
    # 20 + 15 + 10 + 25 + 20 + 15 + 10 = 115 -> capped at 100
    assert score == 100


def test_score_ai_consulting_vertical_counts_as_target() -> None:
    L = _lead(email="a@b.com", company="X", vertical=Vertical.ai_consulting)
    # 20 + 15 + 25 = 60
    assert LeadGenerationAgent.score_lead(L) == 60


def test_score_inbound_email_warmer_than_manual() -> None:
    base = _lead(email="x@y.com", company="A", vertical=Vertical.healthcare)
    inbound = _lead(
        email="x@y.com", company="A", vertical=Vertical.healthcare,
        source=LeadSource.inbound_email,
    )
    assert LeadGenerationAgent.score_lead(inbound) > LeadGenerationAgent.score_lead(base)


def test_score_school_vertical_not_treated_as_target() -> None:
    L = _lead(email="a@b.edu", vertical=Vertical.school)
    # 20 (email) only; not in target verticals so no +25
    assert LeadGenerationAgent.score_lead(L) == 20


# ---- follow-up cadence -----------------------------------------------------


def test_followup_terminal_statuses_return_none() -> None:
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    for st in (LeadStatus.won, LeadStatus.lost, LeadStatus.disqualified):
        assert LeadGenerationAgent.recommend_followup(_lead(status=st), now=now) is None


def test_followup_researched_means_today() -> None:
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    L = _lead(status=LeadStatus.researched)
    assert LeadGenerationAgent.recommend_followup(L, now=now) == now


def test_followup_contacted_uses_cadence_from_last_contact() -> None:
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    last = datetime(2026, 5, 20, tzinfo=timezone.utc)
    L = _lead(status=LeadStatus.contacted, last_contacted_at=last)
    result = LeadGenerationAgent.recommend_followup(L, now=now)
    assert result == last + timedelta(days=_CADENCE_DAYS[LeadStatus.contacted])


def test_followup_meeting_short_cadence() -> None:
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    L = _lead(status=LeadStatus.meeting, last_contacted_at=now)
    result = LeadGenerationAgent.recommend_followup(L, now=now)
    assert result == now + timedelta(days=2)


def test_followup_proposal_longer_cadence() -> None:
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    L = _lead(status=LeadStatus.proposal, last_contacted_at=now)
    result = LeadGenerationAgent.recommend_followup(L, now=now)
    assert result == now + timedelta(days=7)


# ---- pipeline prompt --------------------------------------------------------


def _snap(leads, overdue=0, high_score=0) -> _PipelineSnapshot:
    by_status: dict[str, int] = {}
    by_vertical: dict[str, int] = {}
    for L in leads:
        by_status[L.status.value] = by_status.get(L.status.value, 0) + 1
        by_vertical[L.vertical.value] = by_vertical.get(L.vertical.value, 0) + 1
    return _PipelineSnapshot(
        today=datetime(2026, 5, 25, tzinfo=timezone.utc),
        leads=leads,
        by_status=by_status,
        by_vertical=by_vertical,
        overdue_followups=overdue,
        high_score_count=high_score,
    )


def test_prompt_empty_pipeline() -> None:
    prompt = LeadGenerationAgent._build_prompt("anyone hot?", _snap([]))
    assert "open leads: 0" in prompt
    assert "(none)" in prompt
    assert "User asked: anyone hot?" in prompt


def test_prompt_lists_leads_with_signals() -> None:
    leads = [
        _lead(
            name="Alice Smith", company="Township EMS", role="Director",
            vertical=Vertical.ems, status=LeadStatus.contacted, score=85,
            next_followup_at=datetime(2026, 5, 27, tzinfo=timezone.utc),
        ),
    ]
    prompt = LeadGenerationAgent._build_prompt("status", _snap(leads, overdue=0, high_score=1))
    assert "[contacted s85] Alice Smith @ Township EMS, Director" in prompt
    assert "high-score (>=70): 1" in prompt


def test_fallback_text_includes_signals() -> None:
    snap = _snap([_lead(), _lead()], overdue=1, high_score=1)
    text = LeadGenerationAgent._fallback_text(snap)
    assert "2 open lead(s)" in text
    assert "1 overdue follow-up(s)" in text
    assert "1 high-score" in text


# ---- outreach gating --------------------------------------------------------


def test_outreach_prompt_includes_lead_context() -> None:
    L = _lead(
        name="Bob Jones", company="Acme", role="CTO",
        vertical=Vertical.drone, source=LeadSource.referral,
        notes="recent BVLOS waiver application",
    )
    p = LeadGenerationAgent._outreach_prompt(L, OutreachChannel.email, "mention case study")
    assert "Bob Jones" in p
    assert "Acme" in p
    assert "drone" in p
    assert "BVLOS" in p
    assert "case study" in p
    assert "Sign off as Jim" in p


@pytest.mark.asyncio
async def test_draft_outreach_routes_through_approval_gate_even_at_admin(monkeypatch) -> None:
    """Critical: outreach send requires approval even at admin level."""
    agent = LeadGenerationAgent()
    L = _lead(name="Alice", company="Township EMS", email="alice@township-ems.gov")
    captured: dict = {}

    async def fake_generate(*args, **kwargs):
        return SimpleNamespace(text="outreach body", model="x", raw={})

    class FakeSession:
        def add(self, *_): pass
        async def commit(self): pass
        async def refresh(self, obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

    class FakeSessionMaker:
        def __call__(self): return self
        async def __aenter__(self): return FakeSession()
        async def __aexit__(self, *a): return False

    async def fake_propose(self, ctx, action, **kwargs):
        captured["action"] = action
        captured["preview"] = kwargs.get("preview", "")
        return SimpleNamespace(decision=Decision.require_approval, approval=SimpleNamespace(id=uuid.uuid4()))

    monkeypatch.setattr(ollama, "generate", fake_generate)
    monkeypatch.setattr("app.agents.lead_generation.agent.get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(LeadGenerationAgent, "propose", fake_propose)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.admin,
        request_id="r",
        input_text="",
        metadata={},
    )
    msg, outcome = await agent.draft_outreach(ctx, L, channel=OutreachChannel.email)
    assert captured["action"].action_class is ActionClass.action_external_send
    assert captured["action"].name == "outreach.send"
    assert "Alice" in captured["action"].target_summary
    assert "Township EMS" in captured["action"].target_summary
    assert outcome.decision is Decision.require_approval


@pytest.mark.asyncio
async def test_draft_outreach_falls_back_when_llm_down(monkeypatch) -> None:
    agent = LeadGenerationAgent()
    L = _lead(name="Alice", email="alice@example.com")

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    class FakeSession:
        def add(self, *_): pass
        async def commit(self): pass
        async def refresh(self, obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

    class FakeSessionMaker:
        def __call__(self): return self
        async def __aenter__(self): return FakeSession()
        async def __aexit__(self, *a): return False

    async def fake_propose(self, ctx, action, **kwargs):
        return SimpleNamespace(decision=Decision.require_approval, approval=SimpleNamespace(id=uuid.uuid4()))

    monkeypatch.setattr(ollama, "generate", fake_generate)
    monkeypatch.setattr("app.agents.lead_generation.agent.get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(LeadGenerationAgent, "propose", fake_propose)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r",
        input_text="",
        metadata={},
    )
    msg, _ = await agent.draft_outreach(ctx, L)
    assert "Could not draft via LLM" in msg.body_text
