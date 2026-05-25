"""Lead Generation Agent (Roadmap Phase 6).

Owns: lead pipeline, scoring, outreach drafts, follow-up cadence.
Never contacts a lead directly — outreach goes through the same approval
gate as Email send / Proposal submit / Social publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    Lead,
    LeadStatus,
    OutreachChannel,
    OutreachMessage,
    OutreachStatus,
    Vertical,
)
from app.integrations import ollama
from app.security.permissions import ActionClass, PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, lead-gen assistant for Jim Mullen.
Mullen Analytics & AI Consulting (healthcare/EMS/fire/drone/AI consulting).

When drafting outreach:
- 80-150 words. Specific to their org/role.
- Reference one concrete signal you'd actually have noticed (recent grant,
  posting, regulation, news). No generic 'I saw your company is doing great
  things' filler.
- One clear ask (a 20-minute call this week or next).
- No banned words: leverage, synergy, revolutionize, transform.
- Sign off as Jim.
"""


# Follow-up cadence (days) by stage.
_CADENCE_DAYS = {
    LeadStatus.researched: 0,        # ready to contact now
    LeadStatus.contacted: 5,         # 5 days after first contact
    LeadStatus.meeting: 2,           # 2 days post-meeting
    LeadStatus.proposal: 7,          # 7 days after proposal sent
    LeadStatus.won: 0,
    LeadStatus.lost: 0,
    LeadStatus.disqualified: 0,
}


@dataclass
class _PipelineSnapshot:
    today: datetime
    leads: list[Lead]
    by_status: dict[str, int] = field(default_factory=dict)
    by_vertical: dict[str, int] = field(default_factory=dict)
    overdue_followups: int = 0
    high_score_count: int = 0  # score >= 70


class LeadGenerationAgent(BaseAgent):
    name = "lead_generation"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    # ---- handle ------------------------------------------------------------

    async def handle(self, ctx: AgentContext) -> AgentResult:
        snap = await self._collect_pipeline(ctx)
        prompt = self._build_prompt(ctx.input_text, snap)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = result.text.strip()
        except ollama.OllamaError as exc:
            text = self._fallback_text(snap) + f"\n\n(Note: LLM unavailable — {exc})"

        return AgentResult(
            text=text,
            proposed_actions=[],
            memories_to_write=[],
            metadata={
                "agent": self.name,
                "total_leads": len(snap.leads),
                "by_status": snap.by_status,
                "overdue_followups": snap.overdue_followups,
                "high_score_count": snap.high_score_count,
            },
        )

    async def _collect_pipeline(self, ctx: AgentContext) -> _PipelineSnapshot:
        now = datetime.now(timezone.utc)
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Lead)
                .where(
                    Lead.user_id == ctx.user_id,
                    Lead.status.notin_(
                        (LeadStatus.lost, LeadStatus.won, LeadStatus.disqualified)
                    ),
                )
                .order_by(Lead.score.desc(), Lead.next_followup_at.asc().nullslast())
            )
            leads = list(result.scalars())

        by_status: dict[str, int] = {}
        by_vertical: dict[str, int] = {}
        overdue = 0
        high_score = 0
        for L in leads:
            by_status[L.status.value] = by_status.get(L.status.value, 0) + 1
            by_vertical[L.vertical.value] = by_vertical.get(L.vertical.value, 0) + 1
            if L.next_followup_at and L.next_followup_at < now:
                overdue += 1
            if L.score >= 70:
                high_score += 1

        return _PipelineSnapshot(
            today=now,
            leads=leads,
            by_status=by_status,
            by_vertical=by_vertical,
            overdue_followups=overdue,
            high_score_count=high_score,
        )

    @staticmethod
    def _build_prompt(user_input: str, snap: _PipelineSnapshot) -> str:
        lines: list[str] = []
        lines.append(f"Lead pipeline as of {snap.today.strftime('%Y-%m-%d')}:")
        lines.append(f"  open leads: {len(snap.leads)}")
        if snap.by_status:
            lines.append("  by status: " + ", ".join(
                f"{k}={v}" for k, v in sorted(snap.by_status.items())
            ))
        if snap.by_vertical:
            lines.append("  by vertical: " + ", ".join(
                f"{k}={v}" for k, v in sorted(snap.by_vertical.items())
            ))
        if snap.overdue_followups:
            lines.append(f"  overdue follow-ups: {snap.overdue_followups}")
        if snap.high_score_count:
            lines.append(f"  high-score (>=70): {snap.high_score_count}")
        lines.append("")
        lines.append("Top leads:")
        if snap.leads:
            for L in snap.leads[:10]:
                followup = (
                    L.next_followup_at.strftime('%Y-%m-%d')
                    if L.next_followup_at else "no follow-up scheduled"
                )
                org = f" @ {L.company}" if L.company else ""
                role = f", {L.role}" if L.role else ""
                lines.append(
                    f"  - [{L.status.value} s{L.score}] {L.name or '(unnamed)'}{org}{role} "
                    f"({L.vertical.value}, next: {followup})"
                )
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"User asked: {user_input.strip() or 'Walk me through the pipeline.'}")
        lines.append("Respond directly. No preamble. Bullet points OK.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(snap: _PipelineSnapshot) -> str:
        bits = [f"{len(snap.leads)} open lead(s)"]
        if snap.overdue_followups:
            bits.append(f"{snap.overdue_followups} overdue follow-up(s)")
        if snap.high_score_count:
            bits.append(f"{snap.high_score_count} high-score")
        return ", ".join(bits) + "."

    # ---- scoring -----------------------------------------------------------

    @staticmethod
    def score_lead(lead: Lead) -> int:
        """Heuristic ICP scoring 0-100.

        Signals (additive):
          * Has a real email                          +20
          * Has a company name                         +15
          * Has a role specified                       +10
          * In a target vertical                       +25
          * Source = referral                          +20  (warmest)
          * Source = inbound_email                     +15
          * Has substantive notes (>200 chars)         +15
          * Status past 'researched'                   +10 (already moving)

        Capped at 100.
        """
        score = 0
        if "@" in (lead.email or ""):
            score += 20
        if lead.company:
            score += 15
        if lead.role:
            score += 10
        if lead.vertical in (
            Vertical.healthcare, Vertical.ems, Vertical.fire,
            Vertical.drone, Vertical.ai_consulting,
        ):
            score += 25
        if lead.source.value == "referral":
            score += 20
        elif lead.source.value == "inbound_email":
            score += 15
        if len(lead.notes or "") > 200:
            score += 15
        if lead.status is not LeadStatus.researched:
            score += 10
        return min(100, score)

    @staticmethod
    def recommend_followup(lead: Lead, *, now: datetime | None = None) -> datetime | None:
        """Return when to next touch this lead, based on stage + last contact.

        Returns None for terminal stages (won/lost/disqualified) — no follow-up.
        """
        now = now or datetime.now(timezone.utc)
        days = _CADENCE_DAYS.get(lead.status, 0)
        if lead.status in (LeadStatus.won, LeadStatus.lost, LeadStatus.disqualified):
            return None
        if lead.status is LeadStatus.researched:
            # No "last contact" yet — propose today.
            return now
        base = lead.last_contacted_at or now
        return base + timedelta(days=days)

    # ---- outreach draft (gated through approval) --------------------------

    async def draft_outreach(
        self,
        ctx: AgentContext,
        lead: Lead,
        *,
        channel: OutreachChannel = OutreachChannel.email,
        user_instructions: str = "",
    ) -> tuple[OutreachMessage, object]:
        prompt = self._outreach_prompt(lead, channel, user_instructions)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            body = result.text.strip()
            model = result.model
        except ollama.OllamaError as exc:
            body = (
                f"(Could not draft via LLM: {exc})\n\n"
                f"[Write outreach to {lead.name or lead.email} re: {lead.vertical.value}.]"
            )
            model = ""

        subject = ""
        if channel is OutreachChannel.email:
            subject = f"Quick question — {lead.company or 'your team'}"

        msg = OutreachMessage(
            user_id=ctx.user_id,
            lead_id=lead.id,
            channel=channel,
            subject=subject,
            body_text=body,
            status=OutreachStatus.draft,
            generated_by=self.name,
            model=model,
        )
        async with get_sessionmaker()() as session:
            session.add(msg)
            await session.commit()
            await session.refresh(msg)

        target = f"send {channel.value} outreach to {lead.name or lead.email or 'lead'}"
        if lead.company:
            target += f" @ {lead.company}"
        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_external_send,
            name="outreach.send",
            target_summary=target,
        )
        outcome = await self.propose(
            ctx,
            action,
            preview=body[:500],
            payload={
                "outreach_id": str(msg.id),
                "lead_id": str(lead.id),
                "channel": channel.value,
            },
        )
        return msg, outcome

    @staticmethod
    def _outreach_prompt(lead: Lead, channel: OutreachChannel, user_instructions: str) -> str:
        lines = [
            f"Draft a {channel.value} outreach message.",
            f"Recipient: {lead.name or '(name unknown)'}, {lead.role or '(role unknown)'}",
            f"Organization: {lead.company or '(unknown)'}",
            f"Vertical: {lead.vertical.value}",
            f"Source: {lead.source.value}",
            f"Notes from research:\n{lead.notes[:1500] or '(none)'}",
            "",
        ]
        if user_instructions.strip():
            lines.append(f"User instructions: {user_instructions.strip()}")
            lines.append("")
        lines.append(
            "80-150 words. One concrete reference to something real about their org. "
            "One ask (20-min call this week or next). Plain text. Sign off as Jim."
        )
        return "\n".join(lines)
