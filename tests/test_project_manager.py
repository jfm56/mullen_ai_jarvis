"""Project Manager agent: prompt building, fallbacks, weekly report."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.project_manager.agent import (
    ProjectManagerAgent,
    _Portfolio,
    _ProjectSnapshot,
)
from app.integrations import ollama
from app.security.permissions import PermissionLevel


def _proj(name: str, status: str = "active", vertical: str = "ems", priority: int = 3,
          target_days_from_now: int | None = None, value: float = 0.0, client: str = "") -> SimpleNamespace:
    now = datetime(2026, 5, 25, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        slug=name.lower().replace(" ", "-"),
        client=client,
        vertical=SimpleNamespace(value=vertical),
        status=SimpleNamespace(value=status),
        priority=priority,
        target_end_date=now + timedelta(days=target_days_from_now) if target_days_from_now is not None else None,
        value_estimate=value,
    )


def _portfolio(snapshots: list[_ProjectSnapshot]) -> _Portfolio:
    by_status: dict[str, int] = {}
    by_vertical: dict[str, int] = {}
    active_value = 0.0
    for s in snapshots:
        by_status[s.project.status.value] = by_status.get(s.project.status.value, 0) + 1
        by_vertical[s.project.vertical.value] = by_vertical.get(s.project.vertical.value, 0) + 1
        if s.project.status.value == "active":
            active_value += s.project.value_estimate
    return _Portfolio(
        today=datetime(2026, 5, 25, tzinfo=timezone.utc),
        snapshots=snapshots,
        by_status=by_status,
        by_vertical=by_vertical,
        overdue_projects=sum(
            1 for s in snapshots
            if s.project.target_end_date
            and s.project.target_end_date < datetime(2026, 5, 25, tzinfo=timezone.utc)
            and s.project.status.value in ("active", "proposal")
        ),
        total_value_active=active_value,
    )


def test_prompt_empty_portfolio() -> None:
    prompt = ProjectManagerAgent._build_prompt("status?", _portfolio([]))
    assert "total projects: 0" in prompt
    assert "(none)" in prompt
    assert "User asked: status?" in prompt


def test_prompt_lists_projects_with_status_and_risk_signals() -> None:
    snaps = [
        _ProjectSnapshot(
            project=_proj("EMS response analytics", priority=1, vertical="ems",
                          target_days_from_now=-5, client="Township"),
            open_tasks=4,
            overdue_tasks=2,
            risks=[SimpleNamespace(kind=SimpleNamespace(value="risk"), text="x")],
            blockers=[SimpleNamespace(kind=SimpleNamespace(value="blocker"), text="y")],
            recent_notes=[],
        ),
        _ProjectSnapshot(
            project=_proj("Drone fleet dashboard", vertical="drone", priority=3),
            open_tasks=1, overdue_tasks=0,
        ),
    ]
    prompt = ProjectManagerAgent._build_prompt("anything urgent?", _portfolio(snaps))
    assert "EMS response analytics" in prompt
    assert "[Township]" in prompt
    assert "2 overdue tasks" in prompt
    assert "1 blocker(s)" in prompt
    assert "1 risk(s)" in prompt
    assert "overdue (past target date" in prompt


def test_prompt_substitutes_default_input() -> None:
    prompt = ProjectManagerAgent._build_prompt("  ", _portfolio([]))
    assert "User asked: Give me a portfolio summary." in prompt


def test_fallback_text_is_deterministic() -> None:
    port = _portfolio([
        _ProjectSnapshot(project=_proj("a", value=50_000), open_tasks=0, overdue_tasks=0),
        _ProjectSnapshot(
            project=_proj("b", status="proposal", target_days_from_now=-10),
            open_tasks=0, overdue_tasks=0,
        ),
    ])
    text = ProjectManagerAgent._fallback_text(port)
    assert "2 projects" in text
    assert "1 overdue" in text
    assert "$50,000 active value" in text


def test_weekly_prompt_includes_per_project_section() -> None:
    snaps = [
        _ProjectSnapshot(
            project=_proj("EMS analytics", vertical="ems", client="Township"),
            open_tasks=3,
            overdue_tasks=1,
            recent_notes=[
                SimpleNamespace(
                    kind=SimpleNamespace(value="win"),
                    text="onboarding call went well",
                    created_at=datetime(2026, 5, 23, tzinfo=timezone.utc),
                ),
            ],
        ),
    ]
    prompt = ProjectManagerAgent._build_weekly_prompt(_portfolio(snaps))
    assert "## EMS analytics" in prompt
    assert "client: Township" in prompt
    assert "open tasks: 3 (1 overdue)" in prompt
    assert "win] onboarding call" in prompt
    assert "Write a single weekly status report" in prompt


def test_fallback_weekly_is_per_project() -> None:
    snaps = [
        _ProjectSnapshot(project=_proj("a"), open_tasks=2, overdue_tasks=1),
        _ProjectSnapshot(
            project=_proj("b"),
            open_tasks=0,
            overdue_tasks=0,
            blockers=[SimpleNamespace(kind=SimpleNamespace(value="blocker"))],
        ),
    ]
    text = ProjectManagerAgent._fallback_weekly(_portfolio(snaps))
    assert "- a [active]: 2 open task(s), 1 overdue" in text
    assert "- b [active]: 0 open task(s), 0 overdue, 1 blocker(s)" in text


@pytest.mark.asyncio
async def test_handle_uses_fallback_when_llm_down(monkeypatch) -> None:
    agent = ProjectManagerAgent()

    async def fake_collect(self, ctx):  # noqa: ARG001
        return _portfolio([
            _ProjectSnapshot(project=_proj("only", value=10_000), open_tasks=0, overdue_tasks=0),
        ])

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ProjectManagerAgent, "_collect_portfolio", fake_collect)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r",
        input_text="status?",
        metadata={},
    )
    result = await agent.handle(ctx)
    assert "1 projects" in result.text
    assert "LLM unavailable" in result.text
    assert result.metadata["total_projects"] == 1
    assert result.metadata["active_value"] == 10_000


@pytest.mark.asyncio
async def test_weekly_report_falls_back_when_llm_down(monkeypatch) -> None:
    agent = ProjectManagerAgent()

    async def fake_collect(self, ctx):  # noqa: ARG001
        return _portfolio([
            _ProjectSnapshot(project=_proj("only"), open_tasks=2, overdue_tasks=1),
        ])

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ProjectManagerAgent, "_collect_portfolio", fake_collect)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.read_only,
        request_id="r",
        input_text="",
        metadata={},
    )
    text = await agent.weekly_report(ctx)
    assert text.startswith("Weekly status —")
    assert "only" in text
    assert "1 overdue" in text
