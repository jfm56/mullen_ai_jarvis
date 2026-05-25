"""Business Development agent: pipeline summary + proposal draft gating."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.business_development.agent import BusinessDevelopmentAgent, _Pipeline
from app.integrations import ollama
from app.security.permissions import ActionClass, Decision, PermissionLevel


def _opp(title: str, status: str = "watching", kind: str = "rfp",
         vertical: str = "ems", days_until_deadline: int | None = None,
         value: float = 0.0, agency: str = "") -> SimpleNamespace:
    now = datetime(2026, 5, 25, 12, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        agency_or_company=agency,
        kind=SimpleNamespace(value=kind),
        vertical=SimpleNamespace(value=vertical),
        status=SimpleNamespace(value=status),
        deadline=now + timedelta(days=days_until_deadline) if days_until_deadline is not None else None,
        value_estimate=value,
        notes="",
    )


def _pipeline(opps: list[SimpleNamespace]) -> _Pipeline:
    now = datetime(2026, 5, 25, 12, tzinfo=timezone.utc)
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_vertical: dict[str, int] = {}
    d7 = d30 = 0
    for o in opps:
        by_status[o.status.value] = by_status.get(o.status.value, 0) + 1
        by_kind[o.kind.value] = by_kind.get(o.kind.value, 0) + 1
        by_vertical[o.vertical.value] = by_vertical.get(o.vertical.value, 0) + 1
        if o.deadline:
            delta = o.deadline - now
            if timedelta(0) <= delta <= timedelta(days=7):
                d7 += 1
            if timedelta(0) <= delta <= timedelta(days=30):
                d30 += 1
    return _Pipeline(
        today=now,
        opportunities=opps,
        by_status=by_status,
        by_kind=by_kind,
        by_vertical=by_vertical,
        deadlines_within_7d=d7,
        deadlines_within_30d=d30,
    )


def test_prompt_empty_pipeline() -> None:
    prompt = BusinessDevelopmentAgent._build_prompt("status?", _pipeline([]))
    assert "total open: 0" in prompt
    assert "(none)" in prompt


def test_prompt_lists_opportunities_sorted_by_deadline() -> None:
    opps = [
        _opp("Far one", days_until_deadline=45),
        _opp("Close one", days_until_deadline=3, kind="grant", agency="NIH", value=250_000),
    ]
    pipe = _pipeline(opps)
    prompt = BusinessDevelopmentAgent._build_prompt("what's hot?", pipe)
    assert "deadlines within 7 days: 1" in prompt
    assert "deadlines within 30 days: 1" in prompt
    assert "Close one" in prompt
    assert "[NIH]" in prompt
    assert "$250,000" in prompt


def test_fallback_text_includes_deadline_counts() -> None:
    pipe = _pipeline([
        _opp("a", days_until_deadline=2),
        _opp("b", days_until_deadline=20),
    ])
    text = BusinessDevelopmentAgent._fallback_text(pipe)
    assert "2 open opportunities" in text
    assert "1 due in 7 days" in text
    assert "2 due in 30 days" in text


def test_proposal_prompt_includes_opportunity_context() -> None:
    opp = _opp("EMS analytics RFP", agency="Township", vertical="ems")
    opp.notes = "looking for response-time dashboards"
    prompt = BusinessDevelopmentAgent._proposal_prompt(opp, None, "lead with case studies")
    assert "Target: Township" in prompt
    assert "response-time dashboards" in prompt
    assert "User instructions: lead with case studies" in prompt
    assert "problem statement" in prompt
    assert "no markdown" in prompt.lower()


@pytest.mark.asyncio
async def test_draft_proposal_requires_target() -> None:
    agent = BusinessDevelopmentAgent()
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r",
        input_text="",
        metadata={},
    )
    with pytest.raises(ValueError, match="opportunity or project"):
        await agent.draft_proposal(ctx)


@pytest.mark.asyncio
async def test_draft_proposal_routes_through_approval_gate(monkeypatch) -> None:
    """The critical contract: submitting a proposal cannot bypass the approval queue.

    Even with admin permission level, action.external_send must require approval.
    """
    agent = BusinessDevelopmentAgent()
    opp = _opp("Test RFP", agency="Test Agency")

    # Bypass DB persistence.
    captured_action: dict = {}

    async def fake_generate(*args, **kwargs):
        return SimpleNamespace(text="draft body", model="x", raw={})

    class FakeSession:
        def __init__(self): self.committed = False
        def add(self, *_): pass
        async def commit(self): self.committed = True
        async def refresh(self, obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)
            obj.updated_at = datetime.now(timezone.utc)

    class FakeSessionMaker:
        def __call__(self):
            return self
        async def __aenter__(self):
            return FakeSession()
        async def __aexit__(self, *args):
            return False

    async def fake_propose(self, ctx, action, **kwargs):
        captured_action["action"] = action
        captured_action["preview"] = kwargs.get("preview", "")
        captured_action["payload"] = kwargs.get("payload", {})
        return SimpleNamespace(decision=Decision.require_approval, approval=SimpleNamespace(id=uuid.uuid4()))

    monkeypatch.setattr(ollama, "generate", fake_generate)
    monkeypatch.setattr("app.agents.business_development.agent.get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(BusinessDevelopmentAgent, "propose", fake_propose)

    # Even at admin level, the proposal submission must require approval.
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.admin,
        request_id="r",
        input_text="",
        metadata={},
    )
    proposal, outcome = await agent.draft_proposal(ctx, opportunity=opp)
    assert captured_action["action"].action_class is ActionClass.action_external_send
    assert captured_action["action"].name == "proposal.submit"
    assert "Test Agency" in captured_action["action"].target_summary
    assert "draft body" in captured_action["preview"]
    assert outcome.decision is Decision.require_approval
    assert outcome.approval is not None


@pytest.mark.asyncio
async def test_draft_proposal_falls_back_when_llm_down(monkeypatch) -> None:
    agent = BusinessDevelopmentAgent()
    opp = _opp("RFP", agency="Agency")

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
    monkeypatch.setattr("app.agents.business_development.agent.get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(BusinessDevelopmentAgent, "propose", fake_propose)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r",
        input_text="",
        metadata={},
    )
    proposal, _ = await agent.draft_proposal(ctx, opportunity=opp)
    assert "Could not draft via LLM" in proposal.body_text
    assert "Problem statement" in proposal.body_text
