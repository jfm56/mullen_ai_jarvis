"""Email Assistant Agent (Roadmap Phase 4).

Owns: inbox triage, summaries, draft replies, scam detection.
The hard rule from docs/SECURITY.md: never sends. Draft replies are
persisted as `EmailDraft` rows; sending is a separate `action.external_send`
approval that the user settles via the approvals API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.email_assistant.categorize import categorize
from app.agents.email_assistant.scam import detect as detect_scam
from app.db.base import get_sessionmaker
from app.db.models import Email, EmailCategory, EmailDraft
from app.integrations import ollama
from app.security.permissions import ActionClass, PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, Jim Mullen's email assistant.
Be concise. Surface what matters. Never invent senders, subjects, or content.
For drafts: match Jim's tone — direct, warm but not effusive, no marketing fluff.
"""


@dataclass
class InboxSummary:
    total: int
    by_category: dict[str, int]
    flagged_scam: int
    waiting_on_user: int
    overdue_unread_days: int


class EmailAssistantAgent(BaseAgent):
    name = "email_assistant"
    domains = ("personal", "business")
    default_permission_level = PermissionLevel.draft_only

    # ---- handle ------------------------------------------------------------

    async def handle(self, ctx: AgentContext) -> AgentResult:
        summary = await self._summarize_inbox(ctx)
        prompt = self._build_prompt(ctx.input_text, summary)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = result.text.strip()
        except ollama.OllamaError as exc:
            text = self._fallback_text(summary) + f"\n\n(Note: LLM unavailable — {exc})"

        return AgentResult(
            text=text,
            proposed_actions=[],
            memories_to_write=[],
            metadata={
                "agent": self.name,
                "total": summary.total,
                "waiting_on_user": summary.waiting_on_user,
                "flagged_scam": summary.flagged_scam,
                "by_category": summary.by_category,
            },
        )

    async def _summarize_inbox(self, ctx: AgentContext) -> InboxSummary:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(Email).where(
                    Email.user_id == ctx.user_id,
                    Email.domain == ctx.domain,
                    Email.archived.is_(False),
                    Email.received_at >= cutoff,
                )
            )
            emails = list(result.scalars())

        by_cat: dict[str, int] = {}
        for e in emails:
            key = e.category.value if hasattr(e.category, "value") else str(e.category)
            by_cat[key] = by_cat.get(key, 0) + 1

        waiting = sum(1 for e in emails if e.category is EmailCategory.waiting_on_me)
        scams = sum(1 for e in emails if e.is_scam)

        now = datetime.now(timezone.utc)
        oldest_unread = min(
            (e.received_at for e in emails if not e.read and not e.is_scam),
            default=None,
        )
        overdue_days = (now - oldest_unread).days if oldest_unread else 0

        return InboxSummary(
            total=len(emails),
            by_category=by_cat,
            flagged_scam=scams,
            waiting_on_user=waiting,
            overdue_unread_days=max(0, overdue_days),
        )

    @staticmethod
    def _build_prompt(user_input: str, s: InboxSummary) -> str:
        lines: list[str] = []
        lines.append(f"Inbox snapshot (last 7 days): {s.total} messages")
        if s.by_category:
            cats = ", ".join(f"{k}={v}" for k, v in sorted(s.by_category.items()))
            lines.append(f"By category: {cats}")
        if s.waiting_on_user:
            lines.append(f"Waiting on you: {s.waiting_on_user}")
        if s.flagged_scam:
            lines.append(f"Flagged as suspicious: {s.flagged_scam}")
        if s.overdue_unread_days:
            lines.append(f"Oldest unread (non-scam): {s.overdue_unread_days} days")
        lines.append("")
        lines.append(f"User asked: {user_input.strip() or 'Summarize my inbox.'}")
        lines.append("Respond directly. No preamble. Bullet points OK.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(s: InboxSummary) -> str:
        parts = [f"{s.total} emails in last 7 days"]
        if s.waiting_on_user:
            parts.append(f"{s.waiting_on_user} waiting on you")
        if s.flagged_scam:
            parts.append(f"{s.flagged_scam} flagged as scam")
        return ", ".join(parts) + "."

    # ---- enrichment --------------------------------------------------------

    async def enrich(self, email: Email) -> None:
        """Run scam detection + categorization on a single email.

        Safe to call on an already-enriched email — overwrites with fresh values.
        """
        scam = detect_scam(
            from_addr=email.from_addr,
            subject=email.subject,
            body_text=email.body_text,
        )
        email.is_scam = scam.is_likely_scam
        email.scam_score = scam.score
        email.scam_signals = scam.signals

        if scam.is_likely_scam:
            email.category = EmailCategory.suspicious
            return

        cat = await categorize(
            subject=email.subject, body_text=email.body_text, from_addr=email.from_addr
        )
        email.category = cat.category

    # ---- draft reply (gated through approval) -----------------------------

    async def draft_reply(
        self,
        ctx: AgentContext,
        email: Email,
        *,
        user_instructions: str = "",
    ) -> tuple[EmailDraft, object]:
        """Generate a draft reply and queue the *send* as a pending approval.

        Returns the EmailDraft (saved locally) and the ProposalOutcome for
        the send approval. The draft text is written regardless; the send
        approval must be settled (approve=True) by the user via the
        approvals API before anything goes out.
        """
        prompt = self._draft_prompt(email, user_instructions)
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            body = result.text.strip()
            model = result.model
        except ollama.OllamaError as exc:
            body = f"(Could not draft via LLM: {exc})\n\n[Write your reply here.]"
            model = ""

        draft = EmailDraft(
            user_id=ctx.user_id,
            email_id=email.id,
            to_addrs=email.from_addr,  # reply-to
            subject=("Re: " + email.subject) if not email.subject.lower().startswith("re:") else email.subject,
            body_text=body,
            generated_by=self.name,
            model=model,
        )
        async with get_sessionmaker()() as session:
            session.add(draft)
            await session.commit()
            await session.refresh(draft)

        # Queue the send for approval. NEVER bypass this.
        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_external_send,
            name="email.send",
            target_summary=f"send reply to {email.from_addr} re: {email.subject}",
        )
        outcome = await self.propose(
            ctx,
            action,
            preview=body[:500],
            payload={
                "draft_id": str(draft.id),
                "email_id": str(email.id),
                "to": email.from_addr,
                "subject": draft.subject,
            },
        )
        return draft, outcome

    @staticmethod
    def _draft_prompt(email: Email, user_instructions: str) -> str:
        lines = [
            f"You are drafting a reply on Jim's behalf.",
            f"From: {email.from_addr}",
            f"Subject: {email.subject}",
            "",
            "Original message:",
            email.body_text[:4000],
            "",
        ]
        if user_instructions.strip():
            lines.append(f"User instructions: {user_instructions.strip()}")
            lines.append("")
        lines.append(
            "Write the reply body only. No greeting like 'Hi Jim' (you ARE Jim). "
            "No 'Dear sender,' filler. Sign off as Jim. Plain text, no Markdown."
        )
        return "\n".join(lines)
