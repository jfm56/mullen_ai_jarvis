"""Grant Applications API.

Endpoints:
  * Full CRUD on /grants
  * /grants/{id}/initialize          — create section + attachment rows from template
  * /grants/{id}/screen-eligibility  — LLM eligibility verdict
  * /grants/{id}/sections            — list + draft endpoints
  * /grants/{id}/attachments         — CRUD
  * /grants/{id}/assemble            — write packet folder, return path + missing items
  * /grants/{id}/finalize            — queue submission approval
  * /grants/{id}/mark-ready          — flip status to 'ready' after approval is approved
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.grant_writer import GrantWriterAgent
from app.db.base import get_sessionmaker
from app.db.models import (
    EligibilityVerdict,
    FunderType,
    GrantApplication,
    GrantApplicationStatus,
    GrantAttachment,
    GrantSection,
    GrantSectionStatus,
    OrgProfile,
    User,
)
from app.integrations.computer import safe_path
from app.security import approvals as approvals_svc
from app.security.auth import get_current_user
from app.security.permissions import PermissionLevel

router = APIRouter(prefix="/grants", tags=["grants"])


# ---- Views -----------------------------------------------------------------


class GrantSectionView(BaseModel):
    id: str
    kind: str
    title: str
    body_text: str
    order_index: int
    status: str
    word_limit: int
    word_count: int
    generated_by: str
    model: str
    created_at: datetime
    updated_at: datetime


class GrantAttachmentView(BaseModel):
    id: str
    kind: str
    label: str
    required: bool
    file_path: str
    present: bool
    notes: str
    created_at: datetime
    updated_at: datetime


class GrantApplicationView(BaseModel):
    id: str
    org_profile_id: str | None
    opportunity_id: str | None
    funder_type: str
    funder_name: str
    mechanism_code: str
    title: str
    abstract: str
    requested_amount: float
    period_months: int
    status: str
    eligibility_verdict: str
    eligibility_notes: str
    nofo_url: str
    deadline: datetime | None
    bundle_path: str
    submission_approval_id: str | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GrantApplicationCreate(BaseModel):
    funder_type: FunderType
    funder_name: str = Field(default="", max_length=255)
    mechanism_code: str = Field(default="", max_length=64)
    title: str = Field(min_length=1, max_length=512)
    abstract: str = Field(default="", max_length=10_000)
    requested_amount: float = 0.0
    period_months: int = 0
    nofo_url: str = Field(default="", max_length=1024)
    nofo_text: str = Field(default="", max_length=200_000)
    deadline: datetime | None = None
    org_profile_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None


class GrantApplicationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    abstract: str | None = Field(default=None, max_length=10_000)
    requested_amount: float | None = None
    period_months: int | None = None
    status: GrantApplicationStatus | None = None
    nofo_url: str | None = Field(default=None, max_length=1024)
    nofo_text: str | None = Field(default=None, max_length=200_000)
    deadline: datetime | None = None
    org_profile_id: uuid.UUID | None = None
    eligibility_verdict: EligibilityVerdict | None = None
    eligibility_notes: str | None = None


class SectionUpdate(BaseModel):
    body_text: str | None = Field(default=None, max_length=200_000)
    status: GrantSectionStatus | None = None


class SectionDraftRequest(BaseModel):
    user_instructions: str = Field(default="", max_length=2000)


class SectionDraftResponse(BaseModel):
    section: GrantSectionView
    model: str


class AttachmentCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=255)
    required: bool = True
    file_path: str = Field(default="", max_length=1024)
    notes: str = Field(default="", max_length=2000)


class AttachmentUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    required: bool | None = None
    file_path: str | None = Field(default=None, max_length=1024)
    notes: str | None = Field(default=None, max_length=2000)


class AssembleRequest(BaseModel):
    output_root: str = Field(min_length=1, max_length=1024)


class AssembleResponse(BaseModel):
    bundle_path: str
    missing_required: list[str]


class FinalizeRequest(BaseModel):
    permission_level: PermissionLevel = PermissionLevel.ask_before_action


class FinalizeResponse(BaseModel):
    approval_id: str | None
    approval_decision: str


class EligibilityResponse(BaseModel):
    verdict: str
    notes: str


# ---- Converters ------------------------------------------------------------


def _to_view(a: GrantApplication) -> GrantApplicationView:
    return GrantApplicationView(
        id=str(a.id),
        org_profile_id=str(a.org_profile_id) if a.org_profile_id else None,
        opportunity_id=str(a.opportunity_id) if a.opportunity_id else None,
        funder_type=a.funder_type.value,
        funder_name=a.funder_name,
        mechanism_code=a.mechanism_code,
        title=a.title,
        abstract=a.abstract,
        requested_amount=a.requested_amount,
        period_months=a.period_months,
        status=a.status.value,
        eligibility_verdict=a.eligibility_verdict.value,
        eligibility_notes=a.eligibility_notes,
        nofo_url=a.nofo_url,
        deadline=a.deadline,
        bundle_path=a.bundle_path,
        submission_approval_id=str(a.submission_approval_id) if a.submission_approval_id else None,
        submitted_at=a.submitted_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _section_view(s: GrantSection) -> GrantSectionView:
    return GrantSectionView(
        id=str(s.id),
        kind=s.kind, title=s.title, body_text=s.body_text,
        order_index=s.order_index, status=s.status.value,
        word_limit=s.word_limit, word_count=s.word_count,
        generated_by=s.generated_by, model=s.model,
        created_at=s.created_at, updated_at=s.updated_at,
    )


def _att_view(a: GrantAttachment) -> GrantAttachmentView:
    return GrantAttachmentView(
        id=str(a.id), kind=a.kind, label=a.label, required=a.required,
        file_path=a.file_path, present=a.present, notes=a.notes,
        created_at=a.created_at, updated_at=a.updated_at,
    )


async def _load_owned(session, model, _id: uuid.UUID, user_id: uuid.UUID, detail: str):
    row = await session.get(model, _id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail=detail)
    return row


# ---- Application CRUD ------------------------------------------------------


@router.get("", response_model=list[GrantApplicationView])
async def list_grants(
    user: Annotated[User, Depends(get_current_user)],
    grant_status: GrantApplicationStatus | None = Query(default=None, alias="status"),
    funder_type: FunderType | None = Query(default=None),
    open_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[GrantApplicationView]:
    stmt = (
        select(GrantApplication)
        .where(GrantApplication.user_id == user.id)
        .order_by(GrantApplication.deadline.asc().nullslast())
        .limit(limit)
    )
    if grant_status:
        stmt = stmt.where(GrantApplication.status == grant_status)
    elif open_only:
        stmt = stmt.where(
            GrantApplication.status.notin_((
                GrantApplicationStatus.declined,
                GrantApplicationStatus.withdrawn,
            ))
        )
    if funder_type:
        stmt = stmt.where(GrantApplication.funder_type == funder_type)
    async with get_sessionmaker()() as session:
        result = await session.execute(stmt)
        return [_to_view(a) for a in result.scalars()]


@router.post("", response_model=GrantApplicationView, status_code=status.HTTP_201_CREATED)
async def create_grant(
    body: GrantApplicationCreate, user: Annotated[User, Depends(get_current_user)]
) -> GrantApplicationView:
    a = GrantApplication(user_id=user.id, **body.model_dump())
    async with get_sessionmaker()() as session:
        session.add(a)
        await session.commit()
        await session.refresh(a)
    return _to_view(a)


@router.get("/{grant_id}", response_model=GrantApplicationView)
async def get_grant(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> GrantApplicationView:
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        return _to_view(a)


@router.patch("/{grant_id}", response_model=GrantApplicationView)
async def update_grant(
    grant_id: uuid.UUID,
    body: GrantApplicationUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> GrantApplicationView:
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(a, field_name, value)
        await session.commit()
        await session.refresh(a)
        return _to_view(a)


@router.delete("/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_grant(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        await session.delete(a)
        await session.commit()


# ---- Template initialization ----------------------------------------------


@router.post("/{grant_id}/initialize", response_model=dict)
async def initialize(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> dict:
    agent = GrantWriterAgent()
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
    sections_added, attachments_added = await agent.initialize_template(a)
    return {
        "sections_added": sections_added,
        "attachments_added": attachments_added,
    }


# ---- Eligibility ----------------------------------------------------------


@router.post("/{grant_id}/screen-eligibility", response_model=EligibilityResponse)
async def screen_eligibility(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> EligibilityResponse:
    agent = GrantWriterAgent()
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        if a.org_profile_id is None:
            raise HTTPException(
                status_code=400,
                detail="grant has no org_profile_id; set one before screening eligibility",
            )
        org = await session.get(OrgProfile, a.org_profile_id)
        if org is None:
            raise HTTPException(status_code=400, detail="org profile not found")

    verdict, notes = await agent.screen_eligibility(a, org=org)

    async with get_sessionmaker()() as session:
        a2 = await session.get(GrantApplication, grant_id)
        a2.eligibility_verdict = verdict
        a2.eligibility_notes = notes
        if a2.status is GrantApplicationStatus.intake:
            a2.status = GrantApplicationStatus.eligibility
        await session.commit()

    return EligibilityResponse(verdict=verdict.value, notes=notes)


# ---- Sections -------------------------------------------------------------


@router.get("/{grant_id}/sections", response_model=list[GrantSectionView])
async def list_sections(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> list[GrantSectionView]:
    async with get_sessionmaker()() as session:
        await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        result = await session.execute(
            select(GrantSection)
            .where(GrantSection.application_id == grant_id)
            .order_by(GrantSection.order_index)
        )
        return [_section_view(s) for s in result.scalars()]


@router.patch("/{grant_id}/sections/{section_id}", response_model=GrantSectionView)
async def update_section(
    grant_id: uuid.UUID, section_id: uuid.UUID,
    body: SectionUpdate, user: Annotated[User, Depends(get_current_user)],
) -> GrantSectionView:
    async with get_sessionmaker()() as session:
        await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        s = await session.get(GrantSection, section_id)
        if s is None or s.application_id != grant_id:
            raise HTTPException(status_code=404, detail="section not found")
        if body.body_text is not None:
            s.body_text = body.body_text
            s.word_count = len(body.body_text.split())
        if body.status is not None:
            s.status = body.status
        await session.commit()
        await session.refresh(s)
        return _section_view(s)


@router.post("/{grant_id}/sections/{section_id}/draft", response_model=SectionDraftResponse)
async def draft_section(
    grant_id: uuid.UUID, section_id: uuid.UUID,
    body: SectionDraftRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> SectionDraftResponse:
    agent = GrantWriterAgent()
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        s = await session.get(GrantSection, section_id)
        if s is None or s.application_id != grant_id:
            raise HTTPException(status_code=404, detail="section not found")
        # Eager-load sibling sections for context.
        siblings_res = await session.execute(
            select(GrantSection).where(GrantSection.application_id == grant_id)
        )
        a.sections = list(siblings_res.scalars())
        org = await session.get(OrgProfile, a.org_profile_id) if a.org_profile_id else None

    text, model = await agent.draft_section(
        a, s, org=org, user_instructions=body.user_instructions
    )

    async with get_sessionmaker()() as session:
        s2 = await session.get(GrantSection, section_id)
        s2.body_text = text
        s2.word_count = len(text.split())
        s2.model = model
        s2.generated_by = agent.name
        if s2.status is GrantSectionStatus.not_started:
            s2.status = GrantSectionStatus.draft
        # Flip the application to drafting when its first section gets written.
        app = await session.get(GrantApplication, grant_id)
        if app.status in (GrantApplicationStatus.intake, GrantApplicationStatus.eligibility):
            app.status = GrantApplicationStatus.drafting
        await session.commit()
        await session.refresh(s2)
        return SectionDraftResponse(section=_section_view(s2), model=model)


# ---- Attachments ----------------------------------------------------------


@router.get("/{grant_id}/attachments", response_model=list[GrantAttachmentView])
async def list_attachments(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> list[GrantAttachmentView]:
    async with get_sessionmaker()() as session:
        await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        result = await session.execute(
            select(GrantAttachment).where(GrantAttachment.application_id == grant_id)
        )
        return [_att_view(a) for a in result.scalars()]


@router.post(
    "/{grant_id}/attachments", response_model=GrantAttachmentView,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment(
    grant_id: uuid.UUID, body: AttachmentCreate,
    user: Annotated[User, Depends(get_current_user)],
) -> GrantAttachmentView:
    # If a file_path is supplied, it must live inside an allowed root.
    file_path = body.file_path or ""
    present = False
    if file_path:
        try:
            resolved = safe_path.resolve_safe(file_path, must_exist=True)
            file_path = str(resolved)
            present = True
        except safe_path.UnsafePathError as exc:
            raise HTTPException(status_code=400, detail=f"unsafe path: {exc}") from exc

    async with get_sessionmaker()() as session:
        await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        att = GrantAttachment(
            application_id=grant_id, kind=body.kind, label=body.label,
            required=body.required, file_path=file_path, present=present, notes=body.notes,
        )
        session.add(att)
        await session.commit()
        await session.refresh(att)
        return _att_view(att)


@router.patch(
    "/{grant_id}/attachments/{attachment_id}", response_model=GrantAttachmentView
)
async def update_attachment(
    grant_id: uuid.UUID, attachment_id: uuid.UUID,
    body: AttachmentUpdate, user: Annotated[User, Depends(get_current_user)],
) -> GrantAttachmentView:
    async with get_sessionmaker()() as session:
        await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        att = await session.get(GrantAttachment, attachment_id)
        if att is None or att.application_id != grant_id:
            raise HTTPException(status_code=404, detail="attachment not found")

        data = body.model_dump(exclude_unset=True)
        if "file_path" in data and data["file_path"]:
            try:
                resolved = safe_path.resolve_safe(data["file_path"], must_exist=True)
            except safe_path.UnsafePathError as exc:
                raise HTTPException(status_code=400, detail=f"unsafe path: {exc}") from exc
            data["file_path"] = str(resolved)
            att.present = True
        elif "file_path" in data and not data["file_path"]:
            att.present = False
        for k, v in data.items():
            setattr(att, k, v)
        await session.commit()
        await session.refresh(att)
        return _att_view(att)


@router.delete(
    "/{grant_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_attachment(
    grant_id: uuid.UUID, attachment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    async with get_sessionmaker()() as session:
        await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        att = await session.get(GrantAttachment, attachment_id)
        if att is None or att.application_id != grant_id:
            raise HTTPException(status_code=404, detail="attachment not found")
        await session.delete(att)
        await session.commit()


# ---- Bundle + finalize ----------------------------------------------------


@router.post("/{grant_id}/assemble", response_model=AssembleResponse)
async def assemble(
    grant_id: uuid.UUID, body: AssembleRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> AssembleResponse:
    agent = GrantWriterAgent()
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        # Eagerly load sections + attachments for the assembly call.
        a.sections = list((await session.execute(
            select(GrantSection).where(GrantSection.application_id == grant_id)
        )).scalars())
        a.attachments = list((await session.execute(
            select(GrantAttachment).where(GrantAttachment.application_id == grant_id)
        )).scalars())

    ctx = AgentContext(
        user_id=user.id, domain="business",
        permission_level=PermissionLevel.ask_before_action,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )
    try:
        bundle_path, missing = await agent.assemble_bundle(ctx, a, output_root=body.output_root)
    except safe_path.UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=f"unsafe output_root: {exc}") from exc
    return AssembleResponse(bundle_path=bundle_path, missing_required=missing)


@router.post("/{grant_id}/finalize", response_model=FinalizeResponse)
async def finalize(
    grant_id: uuid.UUID, body: FinalizeRequest,
    user: Annotated[User, Depends(get_current_user)],
) -> FinalizeResponse:
    agent = GrantWriterAgent()
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
    ctx = AgentContext(
        user_id=user.id, domain="business",
        permission_level=body.permission_level,
        request_id=str(uuid.uuid4()), input_text="", metadata={},
    )
    outcome = await agent.request_finalize(ctx, a)

    # Tie the approval id back to the application for later /mark-ready.
    if outcome.approval is not None:
        async with get_sessionmaker()() as session:
            a2 = await session.get(GrantApplication, grant_id)
            a2.submission_approval_id = outcome.approval.id
            await session.commit()

    return FinalizeResponse(
        approval_id=str(outcome.approval.id) if outcome.approval else None,
        approval_decision=outcome.decision.value,
    )


@router.post("/{grant_id}/mark-ready", response_model=GrantApplicationView)
async def mark_ready(
    grant_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)],
) -> GrantApplicationView:
    """Flip status to `ready` after the finalize approval has been approved."""
    async with get_sessionmaker()() as session:
        a = await _load_owned(session, GrantApplication, grant_id, user.id, "grant not found")
        if a.submission_approval_id is None:
            raise HTTPException(
                status_code=409, detail="no submission approval queued; call /finalize first"
            )
        approval = await approvals_svc.get(a.submission_approval_id)
        if approval is None or approval.status.value != "approved":
            raise HTTPException(
                status_code=412,
                detail=(
                    f"submission approval is not approved "
                    f"(status={approval.status.value if approval else 'missing'})"
                ),
            )
        a.status = GrantApplicationStatus.ready
        await session.commit()
        await session.refresh(a)
        return _to_view(a)
