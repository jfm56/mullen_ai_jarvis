"""ProactiveAgent: signal ranking + per-signal generators.

Each test mocks just enough of the DB layer to exercise one signal at a
time. Full integration is checked separately via a live DB session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.proactive.agent import (
    ProactiveAgent,
    Suggestion,
    SuggestionPriority,
    _Context,
)
from app.db.models import (
    LeadStatus,
    OpportunityStatus,
    ProjectStatus,
    TaskStatus,
)


NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _ctx() -> _Context:
    return _Context(user_id=uuid.uuid4(), now=NOW)


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Returns a queue of preset results in execute order."""

    def __init__(self, results: list[Any]):
        self._queue = list(results)
        self.executed = 0

    async def execute(self, _stmt):
        self.executed += 1
        if not self._queue:
            return _FakeResult([])
        head = self._queue.pop(0)
        return _FakeResult(head if isinstance(head, list) else [head])


# ---- ranking ---------------------------------------------------------------


def test_priority_rank_orders_urgent_first() -> None:
    suggestions = [
        Suggestion("low", "", SuggestionPriority.low, "task", "1", "/", 1),
        Suggestion("medium", "", SuggestionPriority.medium, "task", "2", "/", 1),
        Suggestion("urgent", "", SuggestionPriority.urgent, "task", "3", "/", 1),
        Suggestion("high", "", SuggestionPriority.high, "task", "4", "/", 1),
    ]
    from app.agents.proactive.agent import _PRIORITY_RANK
    suggestions.sort(key=lambda s: (_PRIORITY_RANK[s.priority], -s.age_hours))
    assert [s.title for s in suggestions] == ["urgent", "high", "medium", "low"]


def test_ties_broken_by_age_oldest_first() -> None:
    a = Suggestion("fresh", "", SuggestionPriority.high, "x", "a", "/", 2)
    b = Suggestion("stale", "", SuggestionPriority.high, "x", "b", "/", 48)
    from app.agents.proactive.agent import _PRIORITY_RANK
    pairs = sorted([a, b], key=lambda s: (_PRIORITY_RANK[s.priority], -s.age_hours))
    assert [s.title for s in pairs] == ["stale", "fresh"]


# ---- overdue tasks ---------------------------------------------------------


@pytest.mark.asyncio
async def test_overdue_task_within_24h_is_high() -> None:
    agent = ProactiveAgent()
    task = SimpleNamespace(
        id=uuid.uuid4(),
        title="Reply to Cooper",
        due_at=NOW - timedelta(hours=3),
        status=TaskStatus.pending,
    )
    session = _FakeSession([[task]])
    suggestions = await agent._overdue_tasks(session, _ctx())
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.priority is SuggestionPriority.high
    assert s.source_kind == "task"
    assert "Reply to Cooper" in s.title


@pytest.mark.asyncio
async def test_overdue_task_past_24h_is_urgent() -> None:
    agent = ProactiveAgent()
    task = SimpleNamespace(
        id=uuid.uuid4(),
        title="Quarterly report",
        due_at=NOW - timedelta(days=3),
        status=TaskStatus.in_progress,
    )
    session = _FakeSession([[task]])
    suggestions = await agent._overdue_tasks(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.urgent
    assert "3d" in suggestions[0].detail


# ---- overdue lead followups ------------------------------------------------


@pytest.mark.asyncio
async def test_high_score_lead_followup_is_urgent() -> None:
    agent = ProactiveAgent()
    lead = SimpleNamespace(
        id=uuid.uuid4(),
        name="Alice Smith",
        email="alice@example.com",
        company="Township EMS",
        status=LeadStatus.contacted,
        score=85,
        vertical=SimpleNamespace(value="ems"),
        next_followup_at=NOW - timedelta(hours=12),
    )
    session = _FakeSession([[lead]])
    suggestions = await agent._overdue_lead_followups(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.urgent
    assert "Township EMS" in suggestions[0].title
    assert suggestions[0].metadata["score"] == 85


@pytest.mark.asyncio
async def test_low_score_lead_followup_is_high_not_urgent() -> None:
    agent = ProactiveAgent()
    lead = SimpleNamespace(
        id=uuid.uuid4(),
        name="Bob",
        email="bob@example.com",
        company="",
        status=LeadStatus.researched,
        score=30,
        vertical=SimpleNamespace(value="other"),
        next_followup_at=NOW - timedelta(hours=6),
    )
    session = _FakeSession([[lead]])
    suggestions = await agent._overdue_lead_followups(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.high


# ---- opportunity deadlines -------------------------------------------------


@pytest.mark.asyncio
async def test_opportunity_within_2_days_is_urgent() -> None:
    agent = ProactiveAgent()
    opp = SimpleNamespace(
        id=uuid.uuid4(),
        title="State EMS grant",
        agency_or_company="NJ Office of EMS",
        deadline=NOW + timedelta(days=1, hours=12),
        status=OpportunityStatus.applying,
        kind=SimpleNamespace(value="grant"),
        vertical=SimpleNamespace(value="ems"),
        value_estimate=75000.0,
    )
    session = _FakeSession([[opp]])
    suggestions = await agent._opportunity_deadlines(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.urgent
    assert "1d" in suggestions[0].title
    assert "NJ Office of EMS" in suggestions[0].title


@pytest.mark.asyncio
async def test_opportunity_within_week_is_high() -> None:
    agent = ProactiveAgent()
    opp = SimpleNamespace(
        id=uuid.uuid4(),
        title="RFP foo",
        agency_or_company="",
        deadline=NOW + timedelta(days=5),
        status=OpportunityStatus.researching,
        kind=SimpleNamespace(value="rfp"),
        vertical=SimpleNamespace(value="healthcare"),
        value_estimate=0.0,
    )
    session = _FakeSession([[opp]])
    suggestions = await agent._opportunity_deadlines(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.high


# ---- stale projects --------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_project_30_days_is_high() -> None:
    agent = ProactiveAgent()
    proj = SimpleNamespace(
        id=uuid.uuid4(),
        name="Cooper staffing model",
        client="Cooper Health",
        vertical=SimpleNamespace(value="healthcare"),
        status=ProjectStatus.active,
        updated_at=NOW - timedelta(days=35),
    )
    session = _FakeSession([[proj]])
    suggestions = await agent._stale_projects(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.high
    assert "35 days" in suggestions[0].title
    assert "Cooper" in suggestions[0].title


@pytest.mark.asyncio
async def test_stale_project_15_days_is_medium() -> None:
    agent = ProactiveAgent()
    proj = SimpleNamespace(
        id=uuid.uuid4(),
        name="X",
        client="",
        vertical=SimpleNamespace(value="other"),
        status=ProjectStatus.active,
        updated_at=NOW - timedelta(days=16),
    )
    session = _FakeSession([[proj]])
    suggestions = await agent._stale_projects(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.medium


# ---- forgotten approvals ---------------------------------------------------


@pytest.mark.asyncio
async def test_3_day_pending_approval_is_urgent() -> None:
    agent = ProactiveAgent()
    approval = SimpleNamespace(
        id=uuid.uuid4(),
        agent="email_assistant",
        action_name="email.send",
        target_summary="reply to alice@example.com re: lunch",
        created_at=NOW - timedelta(days=4),
    )
    session = _FakeSession([[approval]])
    suggestions = await agent._forgotten_approvals(session, _ctx())
    assert suggestions[0].priority is SuggestionPriority.urgent
    assert "96h" in suggestions[0].title
