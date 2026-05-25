"""Marketing Agent (Roadmap Phase 6).

Owns: social/marketing content drafts for healthcare, EMS, fire/public safety,
drone analytics, AI consulting. Never auto-posts — posting goes through the
same approval gate as Email send and Proposal submit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    SocialPlatform,
    SocialPost,
    SocialPostStatus,
    Vertical,
)
from app.integrations import ollama
from app.security.permissions import ActionClass, PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, marketing assistant for Jim Mullen.
Mullen Analytics & AI Consulting works in healthcare, EMS, fire/public safety,
drone operations, and AI consulting.

Voice rules (HARD):
- Write like a practitioner talking to peers, not a SaaS landing page.
- Banned words: revolutionize, leverage, synergy, unlock, supercharge,
  cutting-edge, game-changer, AI-powered (the word "AI" is fine when concrete).
- Specifics beat adjectives. Numbers, names of regs, real metrics.
- Plain text. No Markdown. No hashtag walls.
- Per platform: LinkedIn 1500-2500 chars; X 250-280 chars; blog opener 3-5 paragraphs.
- Sign off as "— Jim" only on LinkedIn / blog.
"""


_PLATFORM_TARGETS = {
    SocialPlatform.linkedin: "LinkedIn post (1500-2500 chars, professional but direct, no hashtag walls)",
    SocialPlatform.facebook: "Facebook post (community-facing, 500-1500 chars)",
    SocialPlatform.x: "X post (250-280 chars max, single tight idea, no thread)",
    SocialPlatform.instagram: "Instagram caption (300-800 chars, visual-first audience)",
    SocialPlatform.blog: "Blog opener (3-5 paragraphs, practitioner-to-practitioner)",
    SocialPlatform.other: "Generic short-form post",
}


_VERTICAL_VOICE = {
    Vertical.healthcare: "clinical, compliance-aware (HIPAA), data-quality focus",
    Vertical.ems: "field-operations focus: response times, dispatch, run-volume",
    Vertical.fire: "public-safety operations: turnout times, call types, mutual aid",
    Vertical.drone: "Part 107/BVLOS, inspection workflows, geospatial output quality",
    Vertical.ai_consulting: "concrete deployments, governance, what works vs. what doesn't",
    Vertical.school: "academic framing, evidence, methodology",
    Vertical.other: "general professional",
}


@dataclass
class _CalendarSnapshot:
    today: datetime
    drafts: int
    scheduled: int
    published_last_7d: int
    by_platform: dict[str, int] = field(default_factory=dict)
    by_vertical: dict[str, int] = field(default_factory=dict)
    upcoming: list[SocialPost] = field(default_factory=list)


class MarketingAgent(BaseAgent):
    name = "marketing"
    domains = ("business", "public")
    default_permission_level = PermissionLevel.draft_only

    # ---- handle ------------------------------------------------------------

    async def handle(self, ctx: AgentContext) -> AgentResult:
        snap = await self._collect_calendar(ctx)
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
                "drafts": snap.drafts,
                "scheduled": snap.scheduled,
                "published_last_7d": snap.published_last_7d,
                "by_platform": snap.by_platform,
                "by_vertical": snap.by_vertical,
            },
        )

    async def _collect_calendar(self, ctx: AgentContext) -> _CalendarSnapshot:
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(SocialPost).where(SocialPost.user_id == ctx.user_id)
            )
            posts = list(result.scalars())

        drafts = sum(1 for p in posts if p.status is SocialPostStatus.draft)
        scheduled = sum(1 for p in posts if p.status is SocialPostStatus.scheduled)
        published_7d = sum(
            1 for p in posts
            if p.status is SocialPostStatus.published
            and p.published_at is not None
            and p.published_at >= week_ago
        )

        by_platform: dict[str, int] = {}
        by_vertical: dict[str, int] = {}
        for p in posts:
            if p.status in (SocialPostStatus.draft, SocialPostStatus.scheduled):
                by_platform[p.platform.value] = by_platform.get(p.platform.value, 0) + 1
                by_vertical[p.vertical.value] = by_vertical.get(p.vertical.value, 0) + 1

        upcoming = sorted(
            (p for p in posts if p.status is SocialPostStatus.scheduled and p.scheduled_for),
            key=lambda p: p.scheduled_for,
        )[:5]

        return _CalendarSnapshot(
            today=now,
            drafts=drafts,
            scheduled=scheduled,
            published_last_7d=published_7d,
            by_platform=by_platform,
            by_vertical=by_vertical,
            upcoming=upcoming,
        )

    @staticmethod
    def _build_prompt(user_input: str, snap: _CalendarSnapshot) -> str:
        lines: list[str] = []
        lines.append(f"Content calendar as of {snap.today.strftime('%Y-%m-%d')}:")
        lines.append(f"  drafts: {snap.drafts}")
        lines.append(f"  scheduled: {snap.scheduled}")
        lines.append(f"  published in last 7 days: {snap.published_last_7d}")
        if snap.by_platform:
            lines.append("  open by platform: " + ", ".join(
                f"{k}={v}" for k, v in sorted(snap.by_platform.items())
            ))
        if snap.by_vertical:
            lines.append("  open by vertical: " + ", ".join(
                f"{k}={v}" for k, v in sorted(snap.by_vertical.items())
            ))
        if snap.upcoming:
            lines.append("")
            lines.append("Upcoming scheduled:")
            for p in snap.upcoming:
                when = p.scheduled_for.strftime("%Y-%m-%d %H:%M")
                lines.append(f"  - {when} [{p.platform.value}/{p.vertical.value}] {p.title or p.body_text[:80]}")
        lines.append("")
        lines.append(f"User asked: {user_input.strip() or 'What does the content calendar look like?'}")
        lines.append("Respond directly. No preamble. Bullet points OK.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(snap: _CalendarSnapshot) -> str:
        bits = [
            f"{snap.drafts} draft(s)",
            f"{snap.scheduled} scheduled",
            f"{snap.published_last_7d} published in last 7 days",
        ]
        return ", ".join(bits) + "."

    # ---- suggest_topics ----------------------------------------------------

    @staticmethod
    def suggest_topics(vertical: Vertical, *, count: int = 5) -> list[str]:
        """Static seed topics by vertical. LLM-driven variants land later."""
        seeds = {
            Vertical.healthcare: [
                "What 'data quality' actually means in a small-clinic dataset",
                "Three EHR export gotchas nobody warns you about",
                "When de-identification isn't enough",
                "Reading a HEDIS rate without getting fooled",
                "Risk adjustment for the not-a-statistician",
            ],
            Vertical.ems: [
                "Why response-time medians lie",
                "Dispatch-to-on-scene: where the seconds actually go",
                "NEMSIS exports for analysts who didn't write them",
                "What a 'high-acuity' patient looks like in run data",
                "Mutual aid analytics for cross-jurisdiction calls",
            ],
            Vertical.fire: [
                "Turnout time vs. total response time — what to measure first",
                "Reading NFIRS without the FRPP filter trap",
                "Call-type drift over a decade",
                "Standards of cover analytics on a budget",
                "What ladder companies and analytics teams have in common",
            ],
            Vertical.drone: [
                "BVLOS waivers: what the rejection letters teach",
                "Inspection-report quality vs. flight-log quality",
                "Geospatial output that downstream GIS teams will actually use",
                "What Part 107 doesn't cover and you should worry about anyway",
                "Battery telemetry as a leading indicator of pilot stress",
            ],
            Vertical.ai_consulting: [
                "A boring AI deployment that worked",
                "Three local-model traps and how we got out",
                "When 'just use the API' is the right answer",
                "What evaluation framework survives contact with a client",
                "Cost per useful answer vs. cost per token",
            ],
            Vertical.school: [
                "What an assignment taught me about model evaluation",
                "Pipeline-vs-essay: what the literature actually says",
            ],
            Vertical.other: [
                "What we shipped this week",
                "Three things that surprised me this month",
            ],
        }
        return list(seeds.get(vertical, seeds[Vertical.other])[:count])

    # ---- draft a post (gated through approval) -----------------------------

    async def draft_post(
        self,
        ctx: AgentContext,
        *,
        platform: SocialPlatform,
        vertical: Vertical,
        topic: str,
        user_instructions: str = "",
    ) -> tuple[SocialPost, object]:
        """Generate a post; queue the *publish* as a pending approval.

        Same gating pattern as Email.send + Proposal.submit — the draft is
        always saved; the platform post requires user approval to go live.
        """
        prompt = self._post_prompt(platform, vertical, topic, user_instructions)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            body = result.text.strip()
            model = result.model
        except ollama.OllamaError as exc:
            body = (
                f"(Could not draft via LLM: {exc})\n\n"
                f"Topic: {topic}\nPlatform: {platform.value}\nVertical: {vertical.value}\n"
                "[Write your post here.]"
            )
            model = ""

        post = SocialPost(
            user_id=ctx.user_id,
            platform=platform,
            vertical=vertical,
            title=topic[:200],
            body_text=body,
            status=SocialPostStatus.draft,
            generated_by=self.name,
            model=model,
        )
        async with get_sessionmaker()() as session:
            session.add(post)
            await session.commit()
            await session.refresh(post)

        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_external_send,
            name="social.publish",
            target_summary=f"publish to {platform.value} ({vertical.value}): {topic[:120]}",
        )
        outcome = await self.propose(
            ctx,
            action,
            preview=body[:500],
            payload={
                "post_id": str(post.id),
                "platform": platform.value,
                "vertical": vertical.value,
            },
        )
        return post, outcome

    @staticmethod
    def _post_prompt(
        platform: SocialPlatform,
        vertical: Vertical,
        topic: str,
        user_instructions: str,
    ) -> str:
        lines = [
            f"Draft a {_PLATFORM_TARGETS[platform]}.",
            f"Vertical voice: {_VERTICAL_VOICE[vertical]}",
            f"Topic: {topic}",
            "",
        ]
        if user_instructions.strip():
            lines.append(f"User instructions: {user_instructions.strip()}")
            lines.append("")
        lines.append(
            "Body only. No title line. No banned words. Specific over general. "
            "Plain text, no Markdown."
        )
        return "\n".join(lines)
