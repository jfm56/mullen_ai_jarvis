"""Business Development Agent (Roadmap Phase 5).

Owns: opportunity pipeline (grants/RFPs/partnerships/cold inbound/referrals),
proposal drafting, deadline surfacing. Submission of a proposal externally
is gated by the same approval pattern as Email send.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.db.base import get_sessionmaker
from app.db.models import Opportunity, OpportunityStatus, Project, Proposal, ProposalStatus
from app.integrations import ollama
from app.security.permissions import ActionClass, PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, business development assistant for Jim Mullen.
He runs Mullen Analytics & AI Consulting — analytics + AI for healthcare, EMS,
fire/public safety, and drone operations.

When drafting outreach or proposals: pragmatic, evidence-led, specific to the
recipient's domain. Avoid AI-vendor cliches ("revolutionize", "leverage",
"synergies"). No Markdown. Sign off as Jim.

When summarizing the pipeline: blockers and approaching deadlines first.
"""


@dataclass
class _Pipeline:
    today: datetime
    opportunities: list[Opportunity]
    by_status: dict[str, int]
    by_kind: dict[str, int]
    by_vertical: dict[str, int]
    deadlines_within_7d: int
    deadlines_within_30d: int


class BusinessDevelopmentAgent(BaseAgent):
    name = "business_development"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    # ---- handle ------------------------------------------------------------

    async def handle(self, ctx: AgentContext) -> AgentResult:
        pipe = await self._collect_pipeline(ctx)
        prompt = self._build_prompt(ctx.input_text, pipe)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = result.text.strip()
        except ollama.OllamaError as exc:
            text = self._fallback_text(pipe) + f"\n\n(Note: LLM unavailable — {exc})"

        return AgentResult(
            text=text,
            proposed_actions=[],
            memories_to_write=[],
            metadata={
                "agent": self.name,
                "total_opportunities": len(pipe.opportunities),
                "by_status": pipe.by_status,
                "deadlines_within_7d": pipe.deadlines_within_7d,
                "deadlines_within_30d": pipe.deadlines_within_30d,
            },
        )

    async def _collect_pipeline(self, ctx: AgentContext) -> _Pipeline:
        now = datetime.now(timezone.utc)
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Opportunity)
                .where(
                    Opportunity.user_id == ctx.user_id,
                    Opportunity.domain == ctx.domain,
                    Opportunity.status.notin_(
                        (OpportunityStatus.lost, OpportunityStatus.dropped, OpportunityStatus.won)
                    ),
                )
                .order_by(Opportunity.deadline.asc().nullslast())
            )
            opps = list(result.scalars())

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

    @staticmethod
    def _build_prompt(user_input: str, pipe: _Pipeline) -> str:
        lines: list[str] = []
        lines.append(f"Opportunity pipeline as of {pipe.today.strftime('%Y-%m-%d')}:")
        lines.append(f"  total open: {len(pipe.opportunities)}")
        if pipe.by_status:
            lines.append("  by status: " + ", ".join(
                f"{k}={v}" for k, v in sorted(pipe.by_status.items())
            ))
        if pipe.by_kind:
            lines.append("  by kind: " + ", ".join(
                f"{k}={v}" for k, v in sorted(pipe.by_kind.items())
            ))
        if pipe.deadlines_within_7d:
            lines.append(f"  deadlines within 7 days: {pipe.deadlines_within_7d}")
        if pipe.deadlines_within_30d:
            lines.append(f"  deadlines within 30 days: {pipe.deadlines_within_30d}")
        lines.append("")
        lines.append("Top opportunities (earliest deadline first):")
        if pipe.opportunities:
            for o in pipe.opportunities[:10]:
                dl = o.deadline.strftime("%Y-%m-%d") if o.deadline else "no deadline"
                val = f", est ${o.value_estimate:,.0f}" if o.value_estimate else ""
                org = f" [{o.agency_or_company}]" if o.agency_or_company else ""
                lines.append(
                    f"  - [{o.status.value}] {o.title}{org} "
                    f"({o.kind.value}/{o.vertical.value}, due {dl}{val})"
                )
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"User asked: {user_input.strip() or 'Walk me through the pipeline.'}")
        lines.append("Respond directly. No preamble. Bullet points OK.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(pipe: _Pipeline) -> str:
        bits = [f"{len(pipe.opportunities)} open opportunities"]
        if pipe.deadlines_within_7d:
            bits.append(f"{pipe.deadlines_within_7d} due in 7 days")
        if pipe.deadlines_within_30d:
            bits.append(f"{pipe.deadlines_within_30d} due in 30 days")
        return ", ".join(bits) + "."

    # ---- proposal draft (gated through approval) --------------------------

    async def draft_proposal(
        self,
        ctx: AgentContext,
        *,
        opportunity: Opportunity | None = None,
        project: Project | None = None,
        user_instructions: str = "",
    ) -> tuple[Proposal, object]:
        """Generate a proposal and queue the SUBMISSION as a pending approval.

        Either `opportunity` or `project` must be provided (the proposal is
        tied to one of them). The proposal body is persisted unconditionally
        as a draft. Submitting the proposal externally requires the user to
        settle the returned approval via /approvals/{id}/decision.
        """
        if opportunity is None and project is None:
            raise ValueError("draft_proposal requires opportunity or project")

        prompt = self._proposal_prompt(opportunity, project, user_instructions)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            body = result.text.strip()
            model = result.model
        except ollama.OllamaError as exc:
            body = (
                f"(Could not draft via LLM: {exc})\n\n"
                "[Outline the proposal here.]\n"
                "1. Problem statement\n2. Proposed approach\n3. Deliverables\n"
                "4. Timeline\n5. Investment\n6. Why Mullen Analytics\n"
            )
            model = ""

        title = (
            f"Proposal: {opportunity.title}" if opportunity else f"Proposal: {project.name if project else 'untitled'}"
        )
        proposal = Proposal(
            user_id=ctx.user_id,
            project_id=project.id if project else None,
            opportunity_id=opportunity.id if opportunity else None,
            title=title,
            body_text=body,
            status=ProposalStatus.draft,
            generated_by=self.name,
            model=model,
        )
        async with get_sessionmaker()() as session:
            session.add(proposal)
            await session.commit()
            await session.refresh(proposal)

        target_desc = (
            f"submit proposal to {opportunity.agency_or_company or opportunity.title}"
            if opportunity
            else f"submit proposal for project {project.name}"
        )
        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_external_send,
            name="proposal.submit",
            target_summary=target_desc,
        )
        outcome = await self.propose(
            ctx,
            action,
            preview=body[:500],
            payload={
                "proposal_id": str(proposal.id),
                "opportunity_id": str(opportunity.id) if opportunity else None,
                "project_id": str(project.id) if project else None,
            },
        )
        return proposal, outcome

    @staticmethod
    def _proposal_prompt(
        opportunity: Opportunity | None,
        project: Project | None,
        user_instructions: str,
    ) -> str:
        lines = ["Draft a proposal on Jim's behalf.", ""]
        if opportunity:
            lines += [
                f"Target: {opportunity.agency_or_company or '(unknown)'}",
                f"Opportunity: {opportunity.title} ({opportunity.kind.value}, vertical: {opportunity.vertical.value})",
                f"Deadline: {opportunity.deadline.strftime('%Y-%m-%d') if opportunity.deadline else 'unstated'}",
                f"Notes from research:\n{opportunity.notes[:2000] or '(none)'}",
            ]
        if project:
            lines += [
                f"Existing client: {project.client or '(internal)'}",
                f"Project context: {project.name} ({project.vertical.value})",
                f"Description:\n{project.description[:2000] or '(none)'}",
            ]
        lines.append("")
        if user_instructions.strip():
            lines.append(f"User instructions: {user_instructions.strip()}")
            lines.append("")
        lines.append(
            "Sections: problem statement, proposed approach, deliverables, "
            "timeline, investment, why Mullen Analytics. Plain text, no Markdown. "
            "Specific to the recipient's domain. No cliches."
        )
        return "\n".join(lines)
