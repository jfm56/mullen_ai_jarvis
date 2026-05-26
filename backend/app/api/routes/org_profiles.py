"""Org Profiles API — the applicant org details used for eligibility checks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import OrgProfile, OrgType, User
from app.security.auth import get_current_user

router = APIRouter(prefix="/org-profiles", tags=["org_profiles"])


class OrgProfileView(BaseModel):
    id: str
    legal_name: str
    short_name: str
    org_type: str
    ein: str
    uei: str
    duns: str
    naics_codes: list[str]
    sam_status: str
    sam_expires_at: datetime | None
    founded_year: int | None
    address: str
    contact_email: str
    contact_phone: str
    website: str
    capabilities_text: str
    boilerplate: dict[str, Any]
    is_default: bool
    created_at: datetime
    updated_at: datetime


class OrgProfileCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    short_name: str = Field(default="", max_length=128)
    org_type: OrgType = OrgType.small_business
    ein: str = Field(default="", max_length=32)
    uei: str = Field(default="", max_length=32)
    duns: str = Field(default="", max_length=32)
    naics_codes: list[str] = Field(default_factory=list)
    sam_status: str = Field(default="", max_length=32)
    sam_expires_at: datetime | None = None
    founded_year: int | None = None
    address: str = Field(default="", max_length=2000)
    contact_email: str = Field(default="", max_length=255)
    contact_phone: str = Field(default="", max_length=64)
    website: str = Field(default="", max_length=512)
    capabilities_text: str = Field(default="", max_length=10_000)
    boilerplate: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class OrgProfileUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    short_name: str | None = Field(default=None, max_length=128)
    org_type: OrgType | None = None
    ein: str | None = Field(default=None, max_length=32)
    uei: str | None = Field(default=None, max_length=32)
    duns: str | None = Field(default=None, max_length=32)
    naics_codes: list[str] | None = None
    sam_status: str | None = Field(default=None, max_length=32)
    sam_expires_at: datetime | None = None
    founded_year: int | None = None
    address: str | None = Field(default=None, max_length=2000)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=512)
    capabilities_text: str | None = Field(default=None, max_length=10_000)
    boilerplate: dict[str, Any] | None = None
    is_default: bool | None = None


def _to_view(o: OrgProfile) -> OrgProfileView:
    return OrgProfileView(
        id=str(o.id),
        legal_name=o.legal_name,
        short_name=o.short_name,
        org_type=o.org_type.value,
        ein=o.ein,
        uei=o.uei,
        duns=o.duns,
        naics_codes=list(o.naics_codes or []),
        sam_status=o.sam_status,
        sam_expires_at=o.sam_expires_at,
        founded_year=o.founded_year,
        address=o.address,
        contact_email=o.contact_email,
        contact_phone=o.contact_phone,
        website=o.website,
        capabilities_text=o.capabilities_text,
        boilerplate=dict(o.boilerplate or {}),
        is_default=o.is_default,
        created_at=o.created_at,
        updated_at=o.updated_at,
    )


@router.get("", response_model=list[OrgProfileView])
async def list_profiles(user: Annotated[User, Depends(get_current_user)]) -> list[OrgProfileView]:
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(OrgProfile).where(OrgProfile.user_id == user.id).order_by(OrgProfile.legal_name)
        )
        return [_to_view(o) for o in result.scalars()]


@router.post("", response_model=OrgProfileView, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: OrgProfileCreate, user: Annotated[User, Depends(get_current_user)]
) -> OrgProfileView:
    o = OrgProfile(user_id=user.id, **body.model_dump())
    async with get_sessionmaker()() as session:
        # Enforce only one default per user.
        if o.is_default:
            await session.execute(
                select(OrgProfile).where(OrgProfile.user_id == user.id, OrgProfile.is_default.is_(True))
            )
            for other in (await session.execute(
                select(OrgProfile).where(
                    OrgProfile.user_id == user.id, OrgProfile.is_default.is_(True)
                )
            )).scalars():
                other.is_default = False
        session.add(o)
        await session.commit()
        await session.refresh(o)
    return _to_view(o)


@router.get("/{profile_id}", response_model=OrgProfileView)
async def get_profile(
    profile_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> OrgProfileView:
    async with get_sessionmaker()() as session:
        o = await session.get(OrgProfile, profile_id)
        if o is None or o.user_id != user.id:
            raise HTTPException(status_code=404, detail="org profile not found")
        return _to_view(o)


@router.patch("/{profile_id}", response_model=OrgProfileView)
async def update_profile(
    profile_id: uuid.UUID,
    body: OrgProfileUpdate,
    user: Annotated[User, Depends(get_current_user)],
) -> OrgProfileView:
    async with get_sessionmaker()() as session:
        o = await session.get(OrgProfile, profile_id)
        if o is None or o.user_id != user.id:
            raise HTTPException(status_code=404, detail="org profile not found")
        for field_name, value in body.model_dump(exclude_unset=True).items():
            setattr(o, field_name, value)
        # Enforce single default.
        if o.is_default:
            for other in (await session.execute(
                select(OrgProfile).where(
                    OrgProfile.user_id == user.id,
                    OrgProfile.is_default.is_(True),
                    OrgProfile.id != o.id,
                )
            )).scalars():
                other.is_default = False
        await session.commit()
        await session.refresh(o)
        return _to_view(o)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: uuid.UUID, user: Annotated[User, Depends(get_current_user)]
) -> None:
    async with get_sessionmaker()() as session:
        o = await session.get(OrgProfile, profile_id)
        if o is None or o.user_id != user.id:
            raise HTTPException(status_code=404, detail="org profile not found")
        await session.delete(o)
        await session.commit()
