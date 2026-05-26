"""Section + attachment template lookups."""

from __future__ import annotations

from app.agents.grant_writer.templates import attachments_for, sections_for
from app.db.models import FunderType


def test_nih_r01_uses_nih_template() -> None:
    secs = sections_for(FunderType.federal_health, "R01")
    kinds = [s.kind for s in secs]
    assert "specific_aims" in kinds
    assert "significance" in kinds
    assert "innovation" in kinds
    assert "approach" in kinds
    # Order is preserved.
    assert kinds.index("specific_aims") < kinds.index("significance") < kinds.index("approach")


def test_nih_r21_falls_through_to_nih_template() -> None:
    assert "specific_aims" in {s.kind for s in sections_for(FunderType.federal_health, "R21")}


def test_federal_health_default_is_samhsa_hrsa_format() -> None:
    secs = sections_for(FunderType.federal_health, "")  # no mechanism code
    kinds = {s.kind for s in secs}
    assert "needs_statement" in kinds
    assert "proposed_approach" in kinds
    assert "evaluation_plan" in kinds
    assert "sustainability" in kinds


def test_fema_afg_uses_afg_template() -> None:
    secs = sections_for(FunderType.federal_public_safety, "AFG")
    kinds = {s.kind for s in secs}
    assert "financial_need" in kinds
    assert "cost_benefit" in kinds
    assert "statement_of_effect" in kinds


def test_doj_cops_uses_doj_template() -> None:
    secs = sections_for(FunderType.federal_public_safety, "COPS")
    kinds = {s.kind for s in secs}
    assert "project_measures" in kinds
    assert "mou_or_partnership_letters" in kinds


def test_state_uses_short_template() -> None:
    secs = sections_for(FunderType.state, "")
    kinds = {s.kind for s in secs}
    # State sections are deliberately simpler.
    assert "needs_statement" in kinds
    assert "project_plan" in kinds
    assert "specific_aims" not in kinds


def test_foundation_uses_loi_template() -> None:
    secs = sections_for(FunderType.foundation, "")
    kinds = [s.kind for s in secs]
    assert kinds[0] == "letter_intro"
    assert "close" in kinds


def test_unknown_funder_type_falls_back_to_generic() -> None:
    # 'other' has no specific template; we get the generic one.
    secs = sections_for(FunderType.other, "")
    kinds = {s.kind for s in secs}
    assert "executive_summary" in kinds
    assert "statement_of_need" in kinds


def test_unknown_mechanism_under_known_family_falls_back_to_family_default() -> None:
    secs = sections_for(FunderType.federal_health, "ZZZ-NONSENSE")
    # Family default for federal_health is SAMHSA/HRSA shape.
    kinds = {s.kind for s in secs}
    assert "needs_statement" in kinds


def test_attachments_nih_r01_includes_biosketches_and_sf424() -> None:
    atts = attachments_for(FunderType.federal_health, "R01")
    kinds = {a.kind for a in atts}
    assert "sf424" in kinds
    assert "biosketch_pi" in kinds
    assert "budget_workbook" in kinds


def test_attachments_fema_afg_skips_indirect_cost_rate() -> None:
    atts = attachments_for(FunderType.federal_public_safety, "AFG")
    kinds = {a.kind for a in atts}
    # AFG attachments are equipment-focused, not the standard federal pack.
    assert "equipment_quotes" in kinds
    assert "indirect_cost_rate" not in kinds


def test_required_flag_is_preserved() -> None:
    atts = attachments_for(FunderType.federal_health, None)
    sf = next((a for a in atts if a.kind == "sf424"), None)
    assert sf is not None
    assert sf.required is True

    optional = next((a for a in atts if a.kind == "biosketch_key_personnel"), None)
    assert optional is not None
    assert optional.required is False
