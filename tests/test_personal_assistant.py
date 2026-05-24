"""Personal Assistant agent: prompt building + LLM-down fallback.

The DB query is patched so this runs without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.personal_assistant.agent import PersonalAssistantAgent, _DayContext
from app.integrations import ollama
from app.security.permissions import PermissionLevel


def _ctx() -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(),
        domain="personal",
        permission_level=PermissionLevel.ask_before_action,
        request_id="req-1",
        input_text="what do I have today?",
        metadata={},
    )


def _day(events=(), open_tasks=(), overdue=(), reminders=()) -> _DayContext:
    return _DayContext(
        today=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
        events=list(events),
        open_tasks=list(open_tasks),
        overdue_tasks=list(overdue),
        upcoming_reminders=list(reminders),
    )


def test_prompt_empty_day_says_none() -> None:
    prompt = PersonalAssistantAgent._build_prompt("hello", _day())
    assert "Calendar events today:" in prompt
    assert "Open tasks:" in prompt
    assert "Upcoming reminders:" in prompt
    assert prompt.count("(none)") == 3
    assert "User said: hello" in prompt


def test_prompt_substitutes_default_input() -> None:
    prompt = PersonalAssistantAgent._build_prompt("   ", _day())
    assert "User said: Give me my day." in prompt


def test_prompt_lists_events_and_tasks() -> None:
    event = SimpleNamespace(
        title="EMS director call",
        start_at=datetime(2026, 5, 24, 14, 0, tzinfo=timezone.utc),
        location="Zoom",
        all_day=False,
    )
    task = SimpleNamespace(
        title="Draft drone proposal",
        priority=SimpleNamespace(value="high"),
        due_at=datetime(2026, 5, 24, 17, 0, tzinfo=timezone.utc),
    )
    prompt = PersonalAssistantAgent._build_prompt(
        "today?", _day(events=[event], open_tasks=[task])
    )
    assert "14:00: EMS director call @ Zoom" in prompt
    assert "[high] Draft drone proposal (due 2026-05-24 17:00)" in prompt


def test_fallback_summary_is_deterministic() -> None:
    day = _day(
        events=[object(), object()],
        open_tasks=[object()],
        overdue=[object()],
        reminders=[object(), object()],
    )
    summary = PersonalAssistantAgent._fallback_summary(day)
    assert "2 events" in summary
    assert "1 open tasks" in summary
    assert "1 overdue" in summary
    assert "2 reminders pending" in summary


@pytest.mark.asyncio
async def test_handle_uses_fallback_when_llm_down(monkeypatch) -> None:
    agent = PersonalAssistantAgent()
    event = SimpleNamespace(
        title="standup",
        start_at=datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
        location="",
        all_day=False,
    )

    async def fake_collect(self, ctx):  # noqa: ARG001
        return _day(events=[event])

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("connection refused")

    monkeypatch.setattr(PersonalAssistantAgent, "_collect_day_context", fake_collect)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    result = await agent.handle(_ctx())
    assert "1 events" in result.text
    assert "LLM unavailable" in result.text
    assert result.metadata["events"] == 1


@pytest.mark.asyncio
async def test_handle_uses_llm_output_when_available(monkeypatch) -> None:
    agent = PersonalAssistantAgent()

    async def fake_collect(self, ctx):  # noqa: ARG001
        return _day()

    async def fake_generate(prompt, *, system=None, **kwargs):
        assert "User said: what do I have today?" in prompt
        assert "Jarvis" in (system or "")
        return SimpleNamespace(text="  Light day. Coffee and code.  ", model="x", raw={})

    monkeypatch.setattr(PersonalAssistantAgent, "_collect_day_context", fake_collect)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    result = await agent.handle(_ctx())
    assert result.text == "Light day. Coffee and code."
    assert result.metadata["events"] == 0
