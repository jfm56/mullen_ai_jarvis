"""Section + attachment templates per funder mechanism.

These are the bones of an application — what sections every funder
expects, what attachments must be included, what the page/word limits
are. The agent uses these to:

  1. Auto-create the right `GrantSection` and `GrantAttachment` rows
     when an application is initialized.
  2. Feed mechanism-specific instructions into the section-drafting prompt.

The templates are intentionally conservative — they cover the common
structure of each funder family, not every quirk of every NOFO. The
NOFO text itself is fed to the LLM during eligibility + drafting so
funder-specific oddities still get caught.

Mechanism resolution:
  * `(funder_type, mechanism_code)` first  — exact match
  * `(funder_type, None)`                  — default for that funder family
  * `("other", None)`                      — generic fallback
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models import FunderType


@dataclass(frozen=True)
class SectionSpec:
    kind: str
    title: str
    order_index: int
    word_limit: int = 0       # 0 = no limit; populated by funder norms
    page_limit: float = 0.0   # approximate; helpful for the prompt
    prompt_hint: str = ""     # one-line instruction baked into the prompt


@dataclass(frozen=True)
class AttachmentSpec:
    kind: str
    label: str
    required: bool = True


# ---- Section template tables ----------------------------------------------


# NIH R-series (R01/R21/R03) — the canonical biomedical research format.
_NIH_R = [
    SectionSpec("project_summary_abstract", "Project Summary / Abstract", 0,
                word_limit=300, page_limit=1,
                prompt_hint="30 lines max. Significance + approach + relevance in lay-accessible terms."),
    SectionSpec("project_narrative", "Project Narrative", 1,
                page_limit=1,
                prompt_hint="2-3 sentences: relevance to public health, plain language."),
    SectionSpec("specific_aims", "Specific Aims", 2,
                page_limit=1,
                prompt_hint="1 page. Hypothesis-driven aims. Each aim a single sentence stem + 2-3 lines."),
    SectionSpec("significance", "Significance", 3,
                page_limit=2,
                prompt_hint="Why this problem matters; gap in current knowledge/practice."),
    SectionSpec("innovation", "Innovation", 4,
                page_limit=1,
                prompt_hint="What's new about the approach. Be concrete; avoid 'novel' as filler."),
    SectionSpec("approach", "Approach", 5,
                page_limit=9,
                prompt_hint="Per aim: rationale, design, methods, analysis, expected results, pitfalls + alternatives."),
    SectionSpec("references", "References Cited", 6,
                prompt_hint="Numbered, cited inline."),
    SectionSpec("budget_narrative", "Budget Justification", 7,
                prompt_hint="Tie each cost to an aim. Personnel %effort + salaries; supplies; subawards; travel."),
    SectionSpec("human_subjects", "Protection of Human Subjects", 8,
                prompt_hint="Only if human subjects are involved; risks, recruitment, IRB plan."),
    SectionSpec("facilities", "Facilities & Other Resources", 9,
                prompt_hint="What we already have that supports the work."),
]


# SAMHSA / HRSA project-narrative format (most non-NIH federal health).
_SAMHSA_HRSA = [
    SectionSpec("project_abstract", "Project Abstract", 0,
                word_limit=300,
                prompt_hint="Brief: project purpose, population, approach, expected outcomes."),
    SectionSpec("needs_statement", "Statement of Need", 1,
                page_limit=3,
                prompt_hint="Data-driven. Cite local/state/national stats for the target population."),
    SectionSpec("proposed_approach", "Proposed Approach", 2,
                page_limit=5,
                prompt_hint="Activities, evidence base, target population, timeline. Tie to needs."),
    SectionSpec("evaluation_plan", "Evaluation Plan", 3,
                page_limit=2,
                prompt_hint="Process + outcome measures. Who collects, how often, how reported."),
    SectionSpec("organizational_capacity", "Organizational Capacity", 4,
                page_limit=2,
                prompt_hint="Past performance, key personnel, partnerships, infrastructure."),
    SectionSpec("sustainability", "Sustainability Plan", 5,
                page_limit=1,
                prompt_hint="How the work continues after the funding period."),
    SectionSpec("budget_narrative", "Budget Narrative", 6,
                prompt_hint="Line-by-line cost basis tied to activities."),
    SectionSpec("work_plan", "Work Plan / Timeline", 7,
                prompt_hint="Quarter-by-quarter milestones; responsible party per row."),
]


# FEMA AFG (Assistance to Firefighters Grant): equipment / vehicles / training.
_FEMA_AFG = [
    SectionSpec("narrative_overview", "Narrative — Project Overview", 0,
                page_limit=2,
                prompt_hint="What the funds will be used for; who benefits; why now."),
    SectionSpec("financial_need", "Financial Need", 1,
                page_limit=2,
                prompt_hint="Why the department cannot fund this from existing budget. Be specific about the gap."),
    SectionSpec("cost_benefit", "Cost-Benefit Analysis", 2,
                page_limit=2,
                prompt_hint="Quantified benefit per dollar. Response-time impact, lives, equipment reach."),
    SectionSpec("statement_of_effect", "Statement of Effect", 3,
                page_limit=2,
                prompt_hint="Operational/safety improvement. Tie to NFPA standards where relevant."),
    SectionSpec("equipment_or_vehicle_spec", "Equipment / Vehicle Specifications", 4,
                prompt_hint="Itemized specs, quantity, unit cost, vendor (if known)."),
    SectionSpec("budget_narrative", "Budget Narrative", 5,
                prompt_hint="Per line item; match cost basis to specifications above."),
]


# DOJ COPS / BJA — law enforcement / public safety adjacent.
_DOJ = [
    SectionSpec("project_abstract", "Project Abstract", 0, word_limit=400),
    SectionSpec("project_narrative", "Project Narrative", 1,
                page_limit=15,
                prompt_hint="Subsections: description of issue, goals/objectives, project design + implementation, capabilities + competencies, plan for collecting performance data."),
    SectionSpec("budget_narrative", "Budget Narrative", 2,
                prompt_hint="Per OJP financial guide. Tie costs to project activities."),
    SectionSpec("project_measures", "Performance Measures", 3,
                prompt_hint="Output + outcome measures aligned with OJP common measures."),
    SectionSpec("mou_or_partnership_letters", "MOU / Partnership Letters", 4,
                prompt_hint="Summary section pointing to attached MOUs."),
]


# State / local — much shorter and more variable.
_STATE = [
    SectionSpec("project_summary", "Project Summary", 0, word_limit=400),
    SectionSpec("needs_statement", "Needs Statement", 1, page_limit=2),
    SectionSpec("project_plan", "Project Plan", 2, page_limit=4,
                prompt_hint="Activities, timeline, who does what."),
    SectionSpec("budget", "Budget", 3,
                prompt_hint="Itemized; brief justification per line."),
    SectionSpec("equipment_list", "Equipment List", 4,
                prompt_hint="Only if applicable. Vendor, quantity, unit cost."),
]


# Foundation / corporate.
_FOUNDATION_LOI = [
    SectionSpec("letter_intro", "Introduction (1-2 paragraphs)", 0,
                prompt_hint="Who we are, why we're writing, the ask in one sentence."),
    SectionSpec("problem_statement", "Problem Statement", 1,
                prompt_hint="The need, the population, the data."),
    SectionSpec("proposed_solution", "Proposed Solution", 2,
                prompt_hint="What we'll do, why we're well-positioned, expected outcomes."),
    SectionSpec("budget_and_ask", "Budget + Ask", 3,
                prompt_hint="Total ask, period, what it covers. One paragraph."),
    SectionSpec("close", "Close", 4,
                prompt_hint="Thank you + next-step ask. One paragraph."),
]


# Generic fallback for any unrecognized funder.
_GENERIC = [
    SectionSpec("executive_summary", "Executive Summary", 0, word_limit=500),
    SectionSpec("statement_of_need", "Statement of Need", 1, page_limit=2),
    SectionSpec("project_description", "Project Description", 2, page_limit=5),
    SectionSpec("evaluation_plan", "Evaluation Plan", 3, page_limit=2),
    SectionSpec("budget_narrative", "Budget Narrative", 4),
    SectionSpec("organizational_capacity", "Organizational Capacity", 5, page_limit=2),
]


_SECTION_TABLE: dict[tuple[FunderType, str | None], list[SectionSpec]] = {
    (FunderType.federal_health, "R01"): _NIH_R,
    (FunderType.federal_health, "R21"): _NIH_R,
    (FunderType.federal_health, "R03"): _NIH_R,
    (FunderType.federal_health, None): _SAMHSA_HRSA,  # default for federal_health if not NIH-coded

    (FunderType.federal_public_safety, "AFG"): _FEMA_AFG,
    (FunderType.federal_public_safety, "AFG-O"): _FEMA_AFG,
    (FunderType.federal_public_safety, "SAFER"): _FEMA_AFG,
    (FunderType.federal_public_safety, "COPS"): _DOJ,
    (FunderType.federal_public_safety, "BJA"): _DOJ,
    (FunderType.federal_public_safety, None): _DOJ,

    (FunderType.state, None): _STATE,
    (FunderType.local, None): _STATE,
    (FunderType.foundation, None): _FOUNDATION_LOI,
    (FunderType.corporate, None): _FOUNDATION_LOI,
    (FunderType.federal_other, None): _GENERIC,
    (FunderType.other, None): _GENERIC,
}


# ---- Attachment templates -------------------------------------------------


_COMMON_FEDERAL = [
    AttachmentSpec("sf424", "SF-424 (Application for Federal Assistance)"),
    AttachmentSpec("project_abstract_form", "Project Abstract Summary"),
    AttachmentSpec("budget_workbook", "Detailed Budget Workbook"),
    AttachmentSpec("indirect_cost_rate", "Indirect Cost Rate Agreement", required=False),
]

_BIOSKETCHES = [
    AttachmentSpec("biosketch_pi", "PI Biosketch (NIH format)"),
    AttachmentSpec("biosketch_key_personnel", "Key Personnel Biosketches", required=False),
]

_ATTACHMENT_TABLE: dict[tuple[FunderType, str | None], list[AttachmentSpec]] = {
    (FunderType.federal_health, "R01"): _COMMON_FEDERAL + _BIOSKETCHES + [
        AttachmentSpec("research_strategy_attachments", "References / Resource Sharing Plan", required=False),
        AttachmentSpec("letters_of_support", "Letters of Support", required=False),
    ],
    (FunderType.federal_health, "R21"): _COMMON_FEDERAL + _BIOSKETCHES,
    (FunderType.federal_health, None): _COMMON_FEDERAL + [
        AttachmentSpec("letters_of_commitment", "Letters of Commitment", required=False),
        AttachmentSpec("biosketch_key_personnel", "Key Personnel Biosketches", required=False),
    ],

    (FunderType.federal_public_safety, "AFG"): [
        AttachmentSpec("sf424", "SF-424"),
        AttachmentSpec("equipment_quotes", "Equipment Quotes / Vendor Specs", required=False),
        AttachmentSpec("financial_audit", "Most recent financial audit", required=False),
    ],
    (FunderType.federal_public_safety, "COPS"): _COMMON_FEDERAL + [
        AttachmentSpec("mou_letters", "MOU / Partnership Letters", required=False),
    ],
    (FunderType.federal_public_safety, "BJA"): _COMMON_FEDERAL + [
        AttachmentSpec("mou_letters", "MOU / Partnership Letters", required=False),
    ],
    (FunderType.federal_public_safety, None): _COMMON_FEDERAL,

    (FunderType.state, None): [
        AttachmentSpec("application_form", "State application form"),
        AttachmentSpec("budget_workbook", "Budget Workbook"),
        AttachmentSpec("certifications", "Certifications + assurances", required=False),
    ],
    (FunderType.local, None): [
        AttachmentSpec("application_form", "Local application form"),
        AttachmentSpec("budget_workbook", "Budget", required=False),
    ],
    (FunderType.foundation, None): [
        AttachmentSpec("budget_summary", "Budget Summary", required=False),
        AttachmentSpec("irs_letter", "IRS 501(c)(3) Determination Letter", required=False),
        AttachmentSpec("financials", "Most recent financials", required=False),
    ],
    (FunderType.corporate, None): [
        AttachmentSpec("budget_summary", "Budget Summary", required=False),
    ],
    (FunderType.federal_other, None): _COMMON_FEDERAL,
    (FunderType.other, None): [],
}


def sections_for(funder_type: FunderType, mechanism_code: str = "") -> list[SectionSpec]:
    """Return the section spec list for `(funder_type, mechanism_code)`.

    Falls back from exact match -> funder default -> generic.
    """
    key_exact = (funder_type, mechanism_code or None)
    if key_exact in _SECTION_TABLE:
        return list(_SECTION_TABLE[key_exact])
    key_family = (funder_type, None)
    if key_family in _SECTION_TABLE:
        return list(_SECTION_TABLE[key_family])
    return list(_GENERIC)


def attachments_for(funder_type: FunderType, mechanism_code: str = "") -> list[AttachmentSpec]:
    key_exact = (funder_type, mechanism_code or None)
    if key_exact in _ATTACHMENT_TABLE:
        return list(_ATTACHMENT_TABLE[key_exact])
    key_family = (funder_type, None)
    if key_family in _ATTACHMENT_TABLE:
        return list(_ATTACHMENT_TABLE[key_family])
    return []
