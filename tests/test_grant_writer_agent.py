"""Grant Writer agent: eligibility parsing, section drafting, finalize gating.

The bundle-assembly happy path is covered by a tmp_path-based test with
allowed roots restricted to the tmp_path (same pattern as test_safe_path).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.base import AgentContext
from app.agents.grant_writer.agent import GrantWriterAgent, _PortfolioSnapshot
from app.db.models import (
    EligibilityVerdict,
    FunderType,
    GrantApplication,
    GrantApplicationStatus,
    GrantAttachment,
    GrantSection,
    GrantSectionStatus,
    OrgProfile,
    OrgType,
)
from app.integrations import ollama
from app.integrations.computer import safe_path
from app.security.permissions import ActionClass, Decision, PermissionLevel


# ---- Eligibility verdict parsing ------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("VERDICT: pass\nREASONS:\n- meets all criteria", EligibilityVerdict.pass_),
    ("Verdict = fail\nBLOCKERS: not eligible", EligibilityVerdict.fail),
    ("verdict: needs_review\nREASONS: ambiguous on NAICS", EligibilityVerdict.needs_review),
    ("VERDICT: needs review", EligibilityVerdict.needs_review),
    ("Looks like a fail to me.", EligibilityVerdict.fail),  # fallback to first match
    ("Probably a pass.", EligibilityVerdict.pass_),
    ("hmm, unclear", EligibilityVerdict.needs_review),
])
def test_parse_eligibility_verdict(text: str, expected: EligibilityVerdict) -> None:
    assert GrantWriterAgent._parse_eligibility_verdict(text) is expected


@pytest.mark.asyncio
async def test_screen_eligibility_uses_llm(monkeypatch) -> None:
    agent = GrantWriterAgent()
    app = SimpleNamespace(
        funder_type=SimpleNamespace(value="federal_health"),
        funder_name="NIH/NIMH",
        mechanism_code="R21",
        title="EMS triage analytics",
        nofo_text="Eligible: small businesses, nonprofits, academic institutions.",
    )
    org = SimpleNamespace(
        legal_name="Mullen Analytics LLC",
        org_type=SimpleNamespace(value="small_business"),
        ein="11-2222222",
        uei="ABC123",
        sam_status="active",
        naics_codes=["541512"],
        capabilities_text="Analytics + AI consulting for EMS/healthcare.",
    )

    captured: dict[str, Any] = {}

    async def fake_generate(prompt, *, system=None, **_kw):
        captured["prompt"] = prompt
        return SimpleNamespace(text="VERDICT: pass\nREASONS:\n- small biz eligible\n", model="x", raw={})

    monkeypatch.setattr(ollama, "generate", fake_generate)
    verdict, notes = await agent.screen_eligibility(app, org=org)
    assert verdict is EligibilityVerdict.pass_
    assert "pass" in notes
    # The prompt should mention the org details + NOFO excerpt.
    assert "Mullen Analytics LLC" in captured["prompt"]
    assert "EMS triage analytics" in captured["prompt"]


@pytest.mark.asyncio
async def test_screen_eligibility_returns_needs_review_when_llm_down(monkeypatch) -> None:
    agent = GrantWriterAgent()
    app = SimpleNamespace(
        funder_type=SimpleNamespace(value="federal_health"),
        funder_name="NIH",
        mechanism_code="",
        title="x",
        nofo_text="",
    )
    org = SimpleNamespace(
        legal_name="x", org_type=SimpleNamespace(value="small_business"),
        ein="", uei="", sam_status="", naics_codes=[], capabilities_text="",
    )

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ollama, "generate", fake_generate)
    verdict, notes = await agent.screen_eligibility(app, org=org)
    assert verdict is EligibilityVerdict.needs_review
    assert "manual review required" in notes


# ---- Section drafting -----------------------------------------------------


@pytest.mark.asyncio
async def test_draft_section_uses_template_hint(monkeypatch) -> None:
    agent = GrantWriterAgent()
    app = SimpleNamespace(
        funder_type=FunderType.federal_health,
        funder_name="NIH",
        mechanism_code="R01",
        title="EMS triage analytics",
        abstract="abstract",
        nofo_text="long NOFO text",
        sections=[],
    )
    section = SimpleNamespace(kind="specific_aims", title="Specific Aims")

    captured: dict[str, Any] = {}

    async def fake_generate(prompt, *, system=None, **_kw):
        captured["prompt"] = prompt
        return SimpleNamespace(text="Aim 1: ...\nAim 2: ...", model="llama-x", raw={})

    monkeypatch.setattr(ollama, "generate", fake_generate)
    text, model = await agent.draft_section(app, section)
    assert text.startswith("Aim 1:")
    assert model == "llama-x"
    # Prompt should reflect the NIH 1-page hint.
    assert "Hypothesis-driven aims" in captured["prompt"] or "1 page" in captured["prompt"]


@pytest.mark.asyncio
async def test_draft_section_falls_back_when_llm_down(monkeypatch) -> None:
    agent = GrantWriterAgent()
    app = SimpleNamespace(
        funder_type=FunderType.foundation, funder_name="Test Foundation",
        mechanism_code="", title="x", abstract="", nofo_text="", sections=[],
    )
    section = SimpleNamespace(kind="letter_intro", title="Introduction (1-2 paragraphs)")

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(ollama, "generate", fake_generate)
    text, model = await agent.draft_section(app, section)
    assert "Could not draft via LLM" in text
    assert model == ""


# ---- Finalize routes through approval gate --------------------------------


@pytest.mark.asyncio
async def test_request_finalize_routes_through_approval_even_at_admin(monkeypatch) -> None:
    """Critical: marking a grant ready-to-submit requires approval at every level."""
    agent = GrantWriterAgent()
    app = SimpleNamespace(
        id=uuid.uuid4(),
        funder_type=SimpleNamespace(value="federal_health"),
        funder_name="NIH",
        title="EMS triage analytics",
        bundle_path="F:/Projects/test",
        deadline=datetime.now(timezone.utc),
        requested_amount=250_000.0,
    )
    captured: dict[str, Any] = {}

    async def fake_propose(self, ctx, action, **kwargs):
        captured["action"] = action
        captured["payload"] = kwargs.get("payload", {})
        return SimpleNamespace(
            decision=Decision.require_approval,
            approval=SimpleNamespace(id=uuid.uuid4()),
        )

    monkeypatch.setattr(GrantWriterAgent, "propose", fake_propose)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        domain="business",
        permission_level=PermissionLevel.admin,
        request_id="r", input_text="", metadata={},
    )
    outcome = await agent.request_finalize(ctx, app)
    assert captured["action"].action_class is ActionClass.action_external_send
    assert captured["action"].name == "grant.finalize_bundle"
    assert "EMS triage analytics" in captured["action"].target_summary
    assert captured["payload"]["grant_application_id"] == str(app.id)
    assert outcome.decision is Decision.require_approval


# ---- Bundle assembly ------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_bundle_writes_files_and_reports_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    # Restrict allowed roots to tmp_path so assemble_bundle's safe_path
    # check accepts the output_root.
    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setattr(safe_path, "_default_roots", lambda: [])

    # Create a fake attachment file inside the sandbox so present=True works.
    att_file = tmp_path / "biosketch.pdf"
    att_file.write_text("biosketch content", encoding="utf-8")

    application = SimpleNamespace(
        id=uuid.uuid4(),
        title="EMS triage analytics for rural districts",
        funder_type=SimpleNamespace(value="federal_health"),
        funder_name="HRSA",
        mechanism_code="HRSA-25-XXX",
        deadline=None,
        eligibility_verdict=SimpleNamespace(value="pass"),
        sections=[
            SimpleNamespace(
                kind="needs_statement", title="Needs Statement",
                order_index=1, body_text="Rural districts face X.",
                status=GrantSectionStatus.ready,
            ),
            SimpleNamespace(
                kind="evaluation_plan", title="Evaluation Plan",
                order_index=3, body_text="(draft)",
                status=GrantSectionStatus.draft,  # NOT ready -> should be reported missing
            ),
        ],
        attachments=[
            SimpleNamespace(
                kind="biosketch_pi", label="PI Biosketch",
                required=True, file_path=str(att_file), present=True,
            ),
            SimpleNamespace(
                kind="budget_workbook", label="Budget Workbook",
                required=True, file_path="", present=False,
            ),
        ],
    )

    # Stub out the DB write that records bundle_path.
    class _Sess:
        async def get(self, _model, _id):
            return SimpleNamespace(bundle_path="")
        async def commit(self): pass
    class _SM:
        def __call__(self): return self
        async def __aenter__(self): return _Sess()
        async def __aexit__(self, *_a): return False

    monkeypatch.setattr("app.agents.grant_writer.agent.get_sessionmaker", lambda: _SM())

    agent = GrantWriterAgent()
    ctx = AgentContext(
        user_id=uuid.uuid4(), domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r", input_text="", metadata={},
    )

    bundle_path, missing = await agent.assemble_bundle(
        ctx, application, output_root=str(tmp_path),
    )

    bundle = Path(bundle_path)
    assert bundle.exists() and bundle.is_dir()
    assert (bundle / "00_NARRATIVE.txt").exists()
    assert (bundle / "CHECKLIST.txt").exists()
    # Per-section file written.
    section_files = list(bundle.glob("*_needs_statement.txt"))
    assert len(section_files) == 1
    assert "Rural districts face X." in section_files[0].read_text(encoding="utf-8")
    # Attachment was copied into attachments/.
    assert (bundle / "attachments" / "biosketch.pdf").exists()
    # Missing items: draft section + missing budget_workbook attachment.
    assert any("evaluation_plan" in m for m in missing)
    assert any("budget_workbook" in m for m in missing)
    # Checklist surfaces missing items.
    checklist = (bundle / "CHECKLIST.txt").read_text(encoding="utf-8")
    assert "Missing required items" in checklist
    assert "evaluation_plan" in checklist


@pytest.mark.asyncio
async def test_assemble_bundle_rejects_output_root_outside_allowed(
    tmp_path: Path, monkeypatch,
) -> None:
    # Allow ONLY tmp_path; try to write into a sibling directory.
    monkeypatch.setenv("JARVIS_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setattr(safe_path, "_default_roots", lambda: [])

    forbidden = tmp_path.parent / "elsewhere"
    forbidden.mkdir(exist_ok=True)

    agent = GrantWriterAgent()
    ctx = AgentContext(
        user_id=uuid.uuid4(), domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r", input_text="", metadata={},
    )
    application = SimpleNamespace(
        id=uuid.uuid4(), title="x",
        funder_type=SimpleNamespace(value="other"), funder_name="", mechanism_code="",
        deadline=None,
        eligibility_verdict=SimpleNamespace(value="pending"),
        sections=[], attachments=[],
    )

    with pytest.raises(safe_path.UnsafePathError):
        await agent.assemble_bundle(ctx, application, output_root=str(forbidden))


# ---- handle is informational ----------------------------------------------


@pytest.mark.asyncio
async def test_handle_uses_fallback_when_llm_down(monkeypatch) -> None:
    agent = GrantWriterAgent()

    async def fake_collect(self, ctx):  # noqa: ARG001
        return _PortfolioSnapshot(
            today=datetime(2026, 5, 25, tzinfo=timezone.utc),
            applications=[],
            by_status={},
            by_funder_type={},
            deadlines_within_14d=0,
            deadlines_within_60d=0,
            total_requested=0,
        )

    async def fake_generate(*args, **kwargs):
        raise ollama.OllamaError("down")

    monkeypatch.setattr(GrantWriterAgent, "_collect_portfolio", fake_collect)
    monkeypatch.setattr(ollama, "generate", fake_generate)

    ctx = AgentContext(
        user_id=uuid.uuid4(), domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id="r", input_text="", metadata={},
    )
    result = await agent.handle(ctx)
    assert "0 open application(s)" in result.text
    assert "LLM unavailable" in result.text
