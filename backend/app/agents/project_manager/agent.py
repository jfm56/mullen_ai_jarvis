"""Project Manager Agent (Roadmap Phase 5).

Owns: portfolio summary across healthcare/EMS/fire/drone/AI verticals + school;
project notes; weekly status report; deadline + risk surfacing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.db.base import get_sessionmaker
from app.db.models import Project, ProjectNote, ProjectNoteKind, ProjectStatus, Task, TaskStatus
from app.integrations import ollama
from app.security.permissions import PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, project manager for Jim Mullen.
Jim runs Mullen Analytics & AI Consulting (healthcare, EMS, fire/public safety,
drone analytics, AI consulting). He is also a student.

Be concise and pragmatic. Surface blockers, risks, and overdue items first.
Use plain text, not Markdown. Never invent project status — only use what's
in the context provided.
"""


@dataclass
class _ProjectSnapshot:
    project: Project
    open_tasks: int
    overdue_tasks: int
    recent_notes: list[ProjectNote] = field(default_factory=list)
    risks: list[ProjectNote] = field(default_factory=list)
    blockers: list[ProjectNote] = field(default_factory=list)


@dataclass
class _Portfolio:
    today: datetime
    snapshots: list[_ProjectSnapshot]
    by_status: dict[str, int]
    by_vertical: dict[str, int]
    overdue_projects: int  # target_end_date passed, status still active/proposal
    total_value_active: float


class ProjectManagerAgent(BaseAgent):
    name = "project_manager"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    async def handle(self, ctx: AgentContext) -> AgentResult:
        portfolio = await self._collect_portfolio(ctx)
        prompt = self._build_prompt(ctx.input_text, portfolio)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = result.text.strip()
        except ollama.OllamaError as exc:
            text = self._fallback_text(portfolio) + f"\n\n(Note: LLM unavailable — {exc})"

        return AgentResult(
            text=text,
            proposed_actions=[],
            memories_to_write=[],
            metadata={
                "agent": self.name,
                "total_projects": len(portfolio.snapshots),
                "overdue_projects": portfolio.overdue_projects,
                "by_status": portfolio.by_status,
                "by_vertical": portfolio.by_vertical,
                "active_value": portfolio.total_value_active,
            },
        )

    async def weekly_report(self, ctx: AgentContext) -> str:
        portfolio = await self._collect_portfolio(ctx)
        prompt = self._build_weekly_prompt(portfolio)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            return result.text.strip()
        except ollama.OllamaError:
            # Deterministic per-project rollup so reports go out even offline.
            return self._fallback_weekly(portfolio)

    # ---- data --------------------------------------------------------------

    async def _collect_portfolio(self, ctx: AgentContext) -> _Portfolio:
        now = datetime.now(timezone.utc)
        snapshots: list[_ProjectSnapshot] = []

        async with get_sessionmaker()() as session:
            projects_res = await session.execute(
                select(Project)
                .where(
                    Project.user_id == ctx.user_id,
                    Project.domain == ctx.domain,
                    Project.status.notin_((ProjectStatus.archived,)),
                )
                .order_by(Project.priority, Project.updated_at.desc())
            )
            projects = list(projects_res.scalars())

            for p in projects:
                tasks_res = await session.execute(
                    select(Task).where(
                        Task.user_id == ctx.user_id,
                        Task.notes.contains(f"#project:{p.slug}"),
                        Task.status.in_((TaskStatus.pending, TaskStatus.in_progress)),
                    )
                )
                open_tasks = list(tasks_res.scalars())
                overdue = sum(1 for t in open_tasks if t.due_at and t.due_at < now)

                notes_res = await session.execute(
                    select(ProjectNote)
                    .where(ProjectNote.project_id == p.id)
                    .order_by(ProjectNote.created_at.desc())
                    .limit(10)
                )
                notes = list(notes_res.scalars())
                snapshots.append(
                    _ProjectSnapshot(
                        project=p,
                        open_tasks=len(open_tasks),
                        overdue_tasks=overdue,
                        recent_notes=notes,
                        risks=[n for n in notes if n.kind is ProjectNoteKind.risk],
                        blockers=[n for n in notes if n.kind is ProjectNoteKind.blocker],
                    )
                )

        by_status: dict[str, int] = {}
        by_vertical: dict[str, int] = {}
        overdue = 0
        active_value = 0.0
        for s in snapshots:
            sk = s.project.status.value
            vk = s.project.vertical.value
            by_status[sk] = by_status.get(sk, 0) + 1
            by_vertical[vk] = by_vertical.get(vk, 0) + 1
            if (
                s.project.target_end_date
                and s.project.target_end_date < now
                and s.project.status in (ProjectStatus.active, ProjectStatus.proposal)
            ):
                overdue += 1
            if s.project.status is ProjectStatus.active:
                active_value += s.project.value_estimate

        return _Portfolio(
            today=now,
            snapshots=snapshots,
            by_status=by_status,
            by_vertical=by_vertical,
            overdue_projects=overdue,
            total_value_active=active_value,
        )

    # ---- prompts -----------------------------------------------------------

    @staticmethod
    def _build_prompt(user_input: str, port: _Portfolio) -> str:
        lines: list[str] = []
        lines.append(f"Portfolio as of {port.today.strftime('%Y-%m-%d')}:")
        lines.append(f"  total projects: {len(port.snapshots)}")
        if port.by_status:
            lines.append("  by status: " + ", ".join(
                f"{k}={v}" for k, v in sorted(port.by_status.items())
            ))
        if port.by_vertical:
            lines.append("  by vertical: " + ", ".join(
                f"{k}={v}" for k, v in sorted(port.by_vertical.items())
            ))
        if port.overdue_projects:
            lines.append(f"  overdue (past target date, still active/in-pursuit): {port.overdue_projects}")
        lines.append("")
        lines.append("Top projects:")
        if port.snapshots:
            for s in port.snapshots[:10]:
                p = s.project
                target = (
                    f", target {p.target_end_date.strftime('%Y-%m-%d')}"
                    if p.target_end_date else ""
                )
                client = f" [{p.client}]" if p.client else ""
                bits = []
                if s.overdue_tasks:
                    bits.append(f"{s.overdue_tasks} overdue tasks")
                if s.blockers:
                    bits.append(f"{len(s.blockers)} blocker(s)")
                if s.risks:
                    bits.append(f"{len(s.risks)} risk(s)")
                meta = " — " + "; ".join(bits) if bits else ""
                lines.append(
                    f"  - [{p.status.value} P{p.priority}] {p.name}{client} "
                    f"({p.vertical.value}{target}){meta}"
                )
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"User asked: {user_input.strip() or 'Give me a portfolio summary.'}")
        lines.append("Respond directly. No preamble. Bullet points OK.")
        return "\n".join(lines)

    @staticmethod
    def _build_weekly_prompt(port: _Portfolio) -> str:
        lines: list[str] = []
        lines.append(f"Weekly status report covering {port.today.strftime('%Y-%m-%d')}.")
        lines.append("")
        for s in port.snapshots:
            p = s.project
            lines.append(f"## {p.name} ({p.vertical.value}, status: {p.status.value})")
            if p.client:
                lines.append(f"   client: {p.client}")
            if p.target_end_date:
                lines.append(f"   target: {p.target_end_date.strftime('%Y-%m-%d')}")
            lines.append(f"   open tasks: {s.open_tasks} ({s.overdue_tasks} overdue)")
            if s.recent_notes:
                lines.append("   recent updates:")
                for n in s.recent_notes[:5]:
                    when = n.created_at.strftime("%m-%d")
                    lines.append(f"     - [{when} {n.kind.value}] {n.text[:160]}")
            lines.append("")
        lines.append("---")
        lines.append(
            "Write a single weekly status report. For each project: one paragraph "
            "covering status, key wins, blockers, and next-week focus. End with "
            "a 'cross-portfolio' section flagging at-risk items. Plain text, no Markdown."
        )
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(port: _Portfolio) -> str:
        bits = [f"{len(port.snapshots)} projects"]
        if port.overdue_projects:
            bits.append(f"{port.overdue_projects} overdue")
        if port.total_value_active:
            bits.append(f"${port.total_value_active:,.0f} active value")
        return ", ".join(bits) + "."

    @staticmethod
    def _fallback_weekly(port: _Portfolio) -> str:
        lines = [f"Weekly status — {port.today.strftime('%Y-%m-%d')}", ""]
        for s in port.snapshots:
            p = s.project
            blockers = f", {len(s.blockers)} blocker(s)" if s.blockers else ""
            lines.append(
                f"- {p.name} [{p.status.value}]: {s.open_tasks} open task(s), "
                f"{s.overdue_tasks} overdue{blockers}"
            )
        return "\n".join(lines)
