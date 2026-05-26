"""Grant Writer Agent (Phase 5b — added on user request).

Owns: grant application lifecycle — eligibility screening, section
drafting per funder mechanism, attachments tracking, and assembling a
final submission bundle. Submission itself is a manual step; the agent
queues a finalize-approval that the user settles to mark the bundle
ready-to-submit.

Hard rules:
  * The agent never submits to Grants.gov / state portals automatically.
    The "submit" action class is `action.external_send` — even when we
    eventually wire a portal integration, it'll go through approval.
  * Assembling the bundle WRITES files inside an allow-listed root
    (verified via app.integrations.computer.safe_path).
  * The eligibility screener never auto-changes a `fail` verdict to
    `pass` — only the user can override.
"""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.grant_writer.templates import (
    AttachmentSpec,
    SectionSpec,
    attachments_for,
    sections_for,
)
from app.db.base import get_sessionmaker
from app.db.models import (
    EligibilityVerdict,
    GrantApplication,
    GrantApplicationStatus,
    GrantAttachment,
    GrantSection,
    GrantSectionStatus,
    OrgProfile,
)
from app.integrations import ollama
from app.integrations.computer import safe_path
from app.security.permissions import ActionClass, PermissionLevel


_SYSTEM_PROMPT = """You are Jarvis, grant writer for Jim Mullen of Mullen Analytics & AI Consulting.

Tone: practitioner-to-reviewer. Specific. Evidence-led. Numbers and citations
beat adjectives.

Banned (HARD): revolutionize, leverage, synergy, unlock, transformative,
cutting-edge, paradigm-shift, holistic. Avoid "AI-powered" as filler; if AI
is part of the project, say what model does what.

Plain text. No Markdown. Match the requested section length within ~10%.
"""


@dataclass
class _PortfolioSnapshot:
    today: datetime
    applications: list[GrantApplication]
    by_status: dict[str, int] = field(default_factory=dict)
    by_funder_type: dict[str, int] = field(default_factory=dict)
    deadlines_within_14d: int = 0
    deadlines_within_60d: int = 0
    total_requested: float = 0.0


class GrantWriterAgent(BaseAgent):
    name = "grant_writer"
    domains = ("business",)
    default_permission_level = PermissionLevel.ask_before_action

    # ---- handle ------------------------------------------------------------

    async def handle(self, ctx: AgentContext) -> AgentResult:
        snap = await self._collect_portfolio(ctx)
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
                "total_applications": len(snap.applications),
                "by_status": snap.by_status,
                "by_funder_type": snap.by_funder_type,
                "deadlines_within_14d": snap.deadlines_within_14d,
                "deadlines_within_60d": snap.deadlines_within_60d,
                "total_requested": snap.total_requested,
            },
        )

    async def _collect_portfolio(self, ctx: AgentContext) -> _PortfolioSnapshot:
        now = datetime.now(timezone.utc)
        async with get_sessionmaker()() as session:
            result = await session.execute(
                select(GrantApplication)
                .where(
                    GrantApplication.user_id == ctx.user_id,
                    GrantApplication.status.notin_((
                        GrantApplicationStatus.declined,
                        GrantApplicationStatus.withdrawn,
                    )),
                )
                .order_by(GrantApplication.deadline.asc().nullslast())
            )
            apps = list(result.scalars())

        by_status: dict[str, int] = {}
        by_funder: dict[str, int] = {}
        d14 = d60 = 0
        total = 0.0
        for a in apps:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            by_funder[a.funder_type.value] = by_funder.get(a.funder_type.value, 0) + 1
            if a.deadline:
                delta = a.deadline - now
                if timedelta(0) <= delta <= timedelta(days=14):
                    d14 += 1
                if timedelta(0) <= delta <= timedelta(days=60):
                    d60 += 1
            total += a.requested_amount

        return _PortfolioSnapshot(
            today=now,
            applications=apps,
            by_status=by_status,
            by_funder_type=by_funder,
            deadlines_within_14d=d14,
            deadlines_within_60d=d60,
            total_requested=total,
        )

    @staticmethod
    def _build_prompt(user_input: str, snap: _PortfolioSnapshot) -> str:
        lines: list[str] = []
        lines.append(f"Grant pipeline as of {snap.today.strftime('%Y-%m-%d')}:")
        lines.append(f"  open applications: {len(snap.applications)}")
        if snap.by_status:
            lines.append("  by status: " + ", ".join(
                f"{k}={v}" for k, v in sorted(snap.by_status.items())
            ))
        if snap.by_funder_type:
            lines.append("  by funder type: " + ", ".join(
                f"{k}={v}" for k, v in sorted(snap.by_funder_type.items())
            ))
        if snap.deadlines_within_14d:
            lines.append(f"  deadlines within 14 days: {snap.deadlines_within_14d}")
        if snap.deadlines_within_60d:
            lines.append(f"  deadlines within 60 days: {snap.deadlines_within_60d}")
        if snap.total_requested:
            lines.append(f"  total requested across open apps: ${snap.total_requested:,.0f}")
        lines.append("")
        lines.append("Top open applications (earliest deadline first):")
        if snap.applications:
            for a in snap.applications[:10]:
                dl = a.deadline.strftime("%Y-%m-%d") if a.deadline else "no deadline"
                amt = f", ${a.requested_amount:,.0f}" if a.requested_amount else ""
                mech = f" {a.mechanism_code}" if a.mechanism_code else ""
                lines.append(
                    f"  - [{a.status.value}] {a.title} "
                    f"({a.funder_type.value}/{a.funder_name}{mech}, due {dl}{amt}, "
                    f"eligibility: {a.eligibility_verdict.value})"
                )
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"User asked: {user_input.strip() or 'Walk me through the grant pipeline.'}")
        lines.append("Respond directly. No preamble. Bullet points OK.")
        return "\n".join(lines)

    @staticmethod
    def _fallback_text(snap: _PortfolioSnapshot) -> str:
        bits = [f"{len(snap.applications)} open application(s)"]
        if snap.deadlines_within_14d:
            bits.append(f"{snap.deadlines_within_14d} due in 14 days")
        if snap.deadlines_within_60d:
            bits.append(f"{snap.deadlines_within_60d} due in 60 days")
        if snap.total_requested:
            bits.append(f"${snap.total_requested:,.0f} requested")
        return ", ".join(bits) + "."

    # ---- initialize sections + attachments --------------------------------

    @staticmethod
    def template_for(application: GrantApplication) -> tuple[list[SectionSpec], list[AttachmentSpec]]:
        secs = sections_for(application.funder_type, application.mechanism_code)
        atts = attachments_for(application.funder_type, application.mechanism_code)
        return secs, atts

    async def initialize_template(self, application: GrantApplication) -> tuple[int, int]:
        """Create GrantSection + GrantAttachment rows for the application.

        Idempotent: skips kinds that already exist. Returns (sections_added,
        attachments_added).
        """
        secs, atts = self.template_for(application)
        added_sec = added_att = 0
        async with get_sessionmaker()() as session:
            existing_secs = await session.execute(
                select(GrantSection.kind).where(
                    GrantSection.application_id == application.id
                )
            )
            existing_sec_kinds = {row[0] for row in existing_secs}
            for spec in secs:
                if spec.kind in existing_sec_kinds:
                    continue
                session.add(GrantSection(
                    application_id=application.id,
                    kind=spec.kind,
                    title=spec.title,
                    order_index=spec.order_index,
                    word_limit=spec.word_limit,
                    status=GrantSectionStatus.not_started,
                    generated_by=self.name,
                ))
                added_sec += 1

            existing_atts = await session.execute(
                select(GrantAttachment.kind).where(
                    GrantAttachment.application_id == application.id
                )
            )
            existing_att_kinds = {row[0] for row in existing_atts}
            for aspec in atts:
                if aspec.kind in existing_att_kinds:
                    continue
                session.add(GrantAttachment(
                    application_id=application.id,
                    kind=aspec.kind,
                    label=aspec.label,
                    required=aspec.required,
                ))
                added_att += 1

            await session.commit()
        return added_sec, added_att

    # ---- eligibility -------------------------------------------------------

    @staticmethod
    def _parse_eligibility_verdict(text: str) -> EligibilityVerdict:
        """Pull a verdict out of LLM output.

        Looks for an explicit `VERDICT: pass|fail|needs_review` line first.
        Falls back to the first matching word in the response.
        """
        m = re.search(r"VERDICT\s*[:=]\s*(pass|fail|needs[_\s-]?review)", text, re.IGNORECASE)
        token = m.group(1).lower() if m else None
        if token is None:
            lowered = text.lower()
            for candidate in ("needs_review", "needs review", "needs-review", "fail", "pass"):
                if candidate in lowered:
                    token = candidate
                    break
        if token is None:
            return EligibilityVerdict.needs_review
        if token == "pass":
            return EligibilityVerdict.pass_
        if token == "fail":
            return EligibilityVerdict.fail
        return EligibilityVerdict.needs_review

    async def screen_eligibility(
        self, application: GrantApplication, *, org: OrgProfile,
    ) -> tuple[EligibilityVerdict, str]:
        """Read NOFO + org profile, return (verdict, notes).

        Never auto-flips a `fail` verdict to `pass`. The user must edit
        the application manually if they disagree.
        """
        nofo = application.nofo_text or "(no NOFO text on file)"
        prompt = (
            "Decide eligibility for this grant.\n\n"
            f"Funder: {application.funder_type.value} / {application.funder_name}\n"
            f"Mechanism: {application.mechanism_code or '(unspecified)'}\n"
            f"Title: {application.title}\n\n"
            "Applicant organization:\n"
            f"  legal_name: {org.legal_name}\n"
            f"  org_type: {org.org_type.value}\n"
            f"  EIN: {org.ein or '(none)'}\n"
            f"  UEI: {org.uei or '(none)'}\n"
            f"  SAM status: {org.sam_status or '(unknown)'}\n"
            f"  NAICS: {', '.join(org.naics_codes) if org.naics_codes else '(none)'}\n"
            f"  capabilities: {(org.capabilities_text or '')[:1000]}\n\n"
            "NOFO text:\n"
            f"{nofo[:6000]}\n\n"
            "Respond in this format exactly:\n"
            "VERDICT: pass | fail | needs_review\n"
            "REASONS:\n"
            "- bullet\n- bullet\n"
            "BLOCKERS:\n"
            "- bullet  (only if fail or needs_review)\n"
        )
        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = result.text.strip()
        except ollama.OllamaError as exc:
            return EligibilityVerdict.needs_review, f"(LLM unavailable — manual review required: {exc})"

        verdict = self._parse_eligibility_verdict(text)
        return verdict, text

    # ---- section drafting -------------------------------------------------

    async def draft_section(
        self,
        application: GrantApplication,
        section: GrantSection,
        *,
        org: OrgProfile | None = None,
        user_instructions: str = "",
    ) -> tuple[str, str]:
        """Generate body_text for one section. Returns (text, model)."""
        spec_lookup = {s.kind: s for s in sections_for(
            application.funder_type, application.mechanism_code
        )}
        spec = spec_lookup.get(section.kind)
        hint = spec.prompt_hint if spec else ""
        length_target = ""
        if spec and spec.word_limit:
            length_target = f"Target length: ~{spec.word_limit} words."
        elif spec and spec.page_limit:
            length_target = f"Target length: ~{int(spec.page_limit * 500)} words ({spec.page_limit} pages)."

        # Pull already-finalized sections for context.
        finalized_context: list[str] = []
        for s in application.sections or []:
            if s.kind == section.kind:
                continue
            if s.status in (GrantSectionStatus.ready, GrantSectionStatus.review) and s.body_text:
                finalized_context.append(f"## {s.title}\n{s.body_text[:1500]}")

        org_block = ""
        if org is not None:
            org_block = (
                f"\nApplicant organization:\n"
                f"  {org.legal_name} ({org.org_type.value})\n"
                f"  capabilities: {(org.capabilities_text or '')[:800]}\n"
            )

        nofo_excerpt = (application.nofo_text or "")[:3000]

        prompt = (
            f"Draft the section titled: {section.title} (kind: {section.kind}).\n"
            f"{hint}\n{length_target}\n\n"
            f"Funder: {application.funder_type.value} / {application.funder_name} "
            f"{application.mechanism_code}\n"
            f"Project title: {application.title}\n"
            f"Abstract:\n{application.abstract[:1500] or '(none)'}\n"
            f"{org_block}"
            + (
                f"\nNOFO excerpt:\n{nofo_excerpt}\n"
                if nofo_excerpt else ""
            )
            + (
                "\nAlready-finalized sections (for consistency):\n" + "\n\n".join(finalized_context)
                if finalized_context else ""
            )
            + (
                f"\n\nUser instructions: {user_instructions.strip()}"
                if user_instructions.strip() else ""
            )
            + "\n\nBody only. No title line. Plain text, no Markdown."
        )

        try:
            result = await ollama.generate(prompt, system=_SYSTEM_PROMPT)
            return result.text.strip(), result.model
        except ollama.OllamaError as exc:
            return (
                f"(Could not draft via LLM: {exc})\n\n"
                f"[Write the {section.title} section here. "
                f"Target: {length_target or 'no specific length'}.]"
            ), ""

    # ---- bundle assembly + finalize-approval -------------------------------

    async def assemble_bundle(
        self,
        ctx: AgentContext,
        application: GrantApplication,
        *,
        output_root: str,
    ) -> tuple[str, list[str]]:
        """Write narrative + per-section files + checklist to a packet folder.

        Returns (bundle_path, missing_required_items). `output_root` MUST be
        inside an allow-listed root (`safe_path.resolve_safe` enforces this).
        """
        root = safe_path.resolve_safe(output_root)
        # Compose a stable, slug-ish folder name for this application.
        slug = re.sub(r"[^a-z0-9]+", "-", application.title.lower()).strip("-")[:60] or "grant"
        bundle = root / f"{slug}-{application.id.hex[:8]}"
        bundle.mkdir(parents=True, exist_ok=True)

        missing: list[str] = []

        # Narrative concatenation in order, plus per-section files.
        narrative_path = bundle / "00_NARRATIVE.txt"
        narrative_lines: list[str] = [
            f"# {application.title}",
            f"# {application.funder_type.value} / {application.funder_name} {application.mechanism_code}",
            f"# Submitted by: (TBD)",
            "",
        ]
        for s in sorted(application.sections or [], key=lambda x: x.order_index):
            if s.status is GrantSectionStatus.skipped:
                continue
            if s.status is not GrantSectionStatus.ready:
                missing.append(f"section:{s.kind} (status={s.status.value})")
                # Still write the draft so the user sees it in the packet.
            per = bundle / f"{s.order_index:02d}_{s.kind}.txt"
            per.write_text(
                f"# {s.title}\n# status: {s.status.value}\n\n{s.body_text}\n",
                encoding="utf-8",
            )
            narrative_lines.append(f"## {s.title}\n{s.body_text}\n")
        narrative_path.write_text("\n".join(narrative_lines), encoding="utf-8")

        # Attachments folder + copy files that already exist.
        attachments_dir = bundle / "attachments"
        attachments_dir.mkdir(exist_ok=True)
        for att in application.attachments or []:
            if not att.present or not att.file_path:
                if att.required:
                    missing.append(f"attachment:{att.kind}")
                continue
            try:
                src = safe_path.resolve_safe(att.file_path, must_exist=True)
            except safe_path.UnsafePathError:
                missing.append(f"attachment:{att.kind} (path outside allowed roots)")
                continue
            dest = attachments_dir / src.name
            shutil.copy2(src, dest)

        # Submission checklist.
        checklist = bundle / "CHECKLIST.txt"
        checklist_lines = [
            f"Submission checklist for: {application.title}",
            f"Funder: {application.funder_type.value} / {application.funder_name} {application.mechanism_code}",
            f"Deadline: {application.deadline.isoformat() if application.deadline else '(none)'}",
            f"Eligibility verdict: {application.eligibility_verdict.value}",
            "",
            "Sections:",
        ]
        for s in sorted(application.sections or [], key=lambda x: x.order_index):
            mark = "[x]" if s.status is GrantSectionStatus.ready else "[ ]"
            checklist_lines.append(f"  {mark} {s.title} ({s.status.value})")
        checklist_lines.append("")
        checklist_lines.append("Attachments:")
        for att in application.attachments or []:
            mark = "[x]" if att.present else "[ ]"
            req = "REQUIRED" if att.required else "optional"
            checklist_lines.append(f"  {mark} {att.label} ({att.kind}, {req})")
        if missing:
            checklist_lines.append("")
            checklist_lines.append("Missing required items:")
            for m in missing:
                checklist_lines.append(f"  - {m}")
        checklist.write_text("\n".join(checklist_lines), encoding="utf-8")

        # Update the application row with the bundle path.
        async with get_sessionmaker()() as session:
            row = await session.get(GrantApplication, application.id)
            if row is not None:
                row.bundle_path = str(bundle)
                await session.commit()

        return str(bundle), missing

    async def request_finalize(
        self, ctx: AgentContext, application: GrantApplication,
    ):
        """Queue an Approval for marking the bundle ready-to-submit.

        Returns (approval_id_or_None, decision). Once the user approves,
        the API layer flips the application's status to `ready`. Actual
        portal submission is a separate manual step in v1.
        """
        action = BaseAgent.action(
            agent=self.name,
            domain=ctx.domain,
            action_class=ActionClass.action_external_send,
            name="grant.finalize_bundle",
            target_summary=(
                f"finalize grant bundle: {application.title} "
                f"({application.funder_type.value}/{application.funder_name})"
            ),
        )
        outcome = await self.propose(
            ctx, action,
            preview=(
                f"Bundle path: {application.bundle_path or '(not assembled)'}\n"
                f"Funder: {application.funder_type.value} / {application.funder_name}\n"
                f"Deadline: {application.deadline}\n"
                f"Requested: ${application.requested_amount:,.0f}\n"
            ),
            payload={
                "grant_application_id": str(application.id),
                "bundle_path": application.bundle_path or "",
            },
        )
        return outcome


# Eagerly-loaded relationship loader used by routes that need sections+attachments.
def with_children():
    return [
        selectinload(GrantApplication.sections),
        selectinload(GrantApplication.attachments),
    ]
