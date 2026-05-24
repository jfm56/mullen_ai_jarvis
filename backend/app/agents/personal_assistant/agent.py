"""Personal Assistant Agent (Roadmap Phase 2).

Owns: daily plan, calendar, tasks, reminders, family scheduling,
voice quick-add. Personal domain only.

The handle() method composes "what's on my plate today" from local DB
state and asks the local LLM to summarize it. Side-effects (creating
a task, adding a calendar event) are exposed as separate methods so
the agent can route through BaseAgent.propose for approval gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.db.base import get_sessionmaker
from app.db.models import CalendarEvent, Reminder, Task, TaskStatus
from app.integrations import ollama
from app.security.permissions import PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, Jim Mullen's personal AI assistant.
Jim runs Mullen Analytics & AI Consulting across healthcare, EMS, fire/public safety,
drone analytics, and AI consulting verticals. He is also a student.

Be concise, calm, and practical. Surface what matters today — don't pad.
When the calendar or task list is empty, say so directly.
Never invent items not present in the context provided to you.
"""


@dataclass
class _DayContext:
    today: datetime
    events: list[CalendarEvent]
    open_tasks: list[Task]
    overdue_tasks: list[Task]
    upcoming_reminders: list[Reminder]


class PersonalAssistantAgent(BaseAgent):
    name = "personal_assistant"
    domains = ("personal",)
    default_permission_level = PermissionLevel.ask_before_action

    async def handle(self, ctx: AgentContext) -> AgentResult:
        day_ctx = await self._collect_day_context(ctx)
        prompt = self._build_prompt(ctx.input_text, day_ctx)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = result.text.strip()
        except ollama.OllamaError as exc:
            # Graceful fallback: deterministic summary so the agent stays useful
            # even when the local LLM is down.
            text = self._fallback_summary(day_ctx) + f"\n\n(Note: LLM unavailable — {exc})"

        return AgentResult(
            text=text,
            proposed_actions=[],
            memories_to_write=[],
            metadata={
                "agent": self.name,
                "events": len(day_ctx.events),
                "open_tasks": len(day_ctx.open_tasks),
                "overdue_tasks": len(day_ctx.overdue_tasks),
                "reminders": len(day_ctx.upcoming_reminders),
            },
        )

    async def _collect_day_context(self, ctx: AgentContext) -> _DayContext:
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        async with get_sessionmaker()() as session:
            events_res = await session.execute(
                select(CalendarEvent)
                .where(
                    CalendarEvent.user_id == ctx.user_id,
                    CalendarEvent.domain == ctx.domain,
                    CalendarEvent.start_at >= start,
                    CalendarEvent.start_at < end,
                )
                .order_by(CalendarEvent.start_at)
            )
            events = list(events_res.scalars())

            open_res = await session.execute(
                select(Task)
                .where(
                    Task.user_id == ctx.user_id,
                    Task.domain == ctx.domain,
                    Task.status.in_((TaskStatus.pending, TaskStatus.in_progress)),
                )
                .order_by(Task.due_at.asc().nullslast())
            )
            open_tasks = list(open_res.scalars())
            overdue = [
                t for t in open_tasks if t.due_at is not None and t.due_at < now
            ]

            rem_res = await session.execute(
                select(Reminder)
                .where(
                    Reminder.user_id == ctx.user_id,
                    Reminder.domain == ctx.domain,
                    Reminder.cancelled.is_(False),
                    Reminder.fired.is_(False),
                    Reminder.fire_at < end,
                )
                .order_by(Reminder.fire_at)
            )
            reminders = list(rem_res.scalars())

        return _DayContext(
            today=now,
            events=events,
            open_tasks=open_tasks,
            overdue_tasks=overdue,
            upcoming_reminders=reminders,
        )

    @staticmethod
    def _build_prompt(user_input: str, day: _DayContext) -> str:
        lines: list[str] = []
        lines.append(f"Today is {day.today.strftime('%A, %B %d, %Y')} (UTC).")
        lines.append("")
        lines.append("Calendar events today:")
        if day.events:
            for e in day.events:
                when = "all day" if e.all_day else e.start_at.strftime("%H:%M")
                loc = f" @ {e.location}" if e.location else ""
                lines.append(f"  - {when}: {e.title}{loc}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("Open tasks:")
        if day.open_tasks:
            for t in day.open_tasks[:20]:
                due = (
                    f" (due {t.due_at.strftime('%Y-%m-%d %H:%M')})"
                    if t.due_at
                    else ""
                )
                lines.append(f"  - [{t.priority.value}] {t.title}{due}")
            if len(day.open_tasks) > 20:
                lines.append(f"  ... and {len(day.open_tasks) - 20} more")
        else:
            lines.append("  (none)")
        if day.overdue_tasks:
            lines.append("")
            lines.append(f"Overdue: {len(day.overdue_tasks)}")
        lines.append("")
        lines.append("Upcoming reminders:")
        if day.upcoming_reminders:
            for r in day.upcoming_reminders[:10]:
                lines.append(f"  - {r.fire_at.strftime('%H:%M')}: {r.text}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("---")
        lines.append(f"User said: {user_input.strip() or 'Give me my day.'}")
        lines.append("Respond directly. No preamble.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(day: _DayContext) -> str:
        parts = [f"Today: {len(day.events)} events, {len(day.open_tasks)} open tasks"]
        if day.overdue_tasks:
            parts.append(f"{len(day.overdue_tasks)} overdue")
        if day.upcoming_reminders:
            parts.append(f"{len(day.upcoming_reminders)} reminders pending")
        return ", ".join(parts) + "."
