"""Phase 5b: org_profiles, grant_applications, grant_sections, grant_attachments.

Revision ID: 0008_phase5b
Revises: 0007_phase7
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_phase5b"
down_revision: Union[str, None] = "0007_phase7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ORG_TYPES = (
    "small_business", "sole_prop", "nonprofit_501c3", "state_local_govt",
    "tribal_govt", "academic", "hospital", "fire_dept", "ems_agency", "other",
)
FUNDER_TYPES = (
    "federal_health", "federal_public_safety", "federal_other",
    "state", "local", "foundation", "corporate", "other",
)
GRANT_APP_STATUSES = (
    "intake", "eligibility", "drafting", "review", "ready",
    "submitted", "awarded", "declined", "withdrawn",
)
ELIGIBILITY_VERDICTS = ("pending", "pass", "fail", "needs_review", "skipped")
SECTION_STATUSES = ("not_started", "draft", "review", "ready", "skipped")


def upgrade() -> None:
    # ---- org_profiles -----------------------------------------------------
    op.create_table(
        "org_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("short_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("org_type", sa.String(32), nullable=False, server_default="small_business"),
        sa.Column("ein", sa.String(32), nullable=False, server_default=""),
        sa.Column("uei", sa.String(32), nullable=False, server_default=""),
        sa.Column("duns", sa.String(32), nullable=False, server_default=""),
        sa.Column("naics_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sam_status", sa.String(32), nullable=False, server_default=""),
        sa.Column("sam_expires_at", sa.DateTime(timezone=True)),
        sa.Column("founded_year", sa.Integer()),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("contact_phone", sa.String(64), nullable=False, server_default=""),
        sa.Column("website", sa.String(512), nullable=False, server_default=""),
        sa.Column("capabilities_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("boilerplate", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_org_profiles_user_legal_name", "org_profiles",
        ["user_id", "legal_name"], unique=True,
    )
    op.create_check_constraint(
        "ck_org_profiles_org_type", "org_profiles",
        "org_type IN ('" + "','".join(ORG_TYPES) + "')",
    )

    # ---- grant_applications ----------------------------------------------
    op.create_table(
        "grant_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org_profiles.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "opportunity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
        ),
        sa.Column("funder_type", sa.String(32), nullable=False),
        sa.Column("funder_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("mechanism_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("period_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="intake"),
        sa.Column(
            "eligibility_verdict", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column("eligibility_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("nofo_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("nofo_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("bundle_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column(
            "submission_approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("outcome_notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_grant_apps_funder_type", "grant_applications", ["funder_type"])
    op.create_index("ix_grant_apps_status", "grant_applications", ["status"])
    op.create_index("ix_grant_apps_deadline", "grant_applications", ["deadline"])
    op.create_index(
        "ix_grant_apps_user_status", "grant_applications", ["user_id", "status"]
    )
    op.create_index(
        "ix_grant_apps_user_deadline", "grant_applications", ["user_id", "deadline"]
    )
    op.create_check_constraint(
        "ck_grant_apps_funder_type", "grant_applications",
        "funder_type IN ('" + "','".join(FUNDER_TYPES) + "')",
    )
    op.create_check_constraint(
        "ck_grant_apps_status", "grant_applications",
        "status IN ('" + "','".join(GRANT_APP_STATUSES) + "')",
    )
    op.create_check_constraint(
        "ck_grant_apps_eligibility_verdict", "grant_applications",
        "eligibility_verdict IN ('" + "','".join(ELIGIBILITY_VERDICTS) + "')",
    )

    # ---- grant_sections ---------------------------------------------------
    op.create_table(
        "grant_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grant_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("word_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_grant_sections_status", "grant_sections", ["status"])
    op.create_index(
        "ix_grant_sections_app_kind", "grant_sections",
        ["application_id", "kind"], unique=True,
    )
    op.create_index(
        "ix_grant_sections_app_order", "grant_sections", ["application_id", "order_index"]
    )
    op.create_check_constraint(
        "ck_grant_sections_status", "grant_sections",
        "status IN ('" + "','".join(SECTION_STATUSES) + "')",
    )

    # ---- grant_attachments -----------------------------------------------
    op.create_table(
        "grant_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grant_applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("file_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_grant_attachments_app_kind", "grant_attachments", ["application_id", "kind"]
    )


def downgrade() -> None:
    op.drop_index("ix_grant_attachments_app_kind", table_name="grant_attachments")
    op.drop_table("grant_attachments")
    op.drop_index("ix_grant_sections_app_order", table_name="grant_sections")
    op.drop_index("ix_grant_sections_app_kind", table_name="grant_sections")
    op.drop_index("ix_grant_sections_status", table_name="grant_sections")
    op.drop_table("grant_sections")
    op.drop_index("ix_grant_apps_user_deadline", table_name="grant_applications")
    op.drop_index("ix_grant_apps_user_status", table_name="grant_applications")
    op.drop_index("ix_grant_apps_deadline", table_name="grant_applications")
    op.drop_index("ix_grant_apps_status", table_name="grant_applications")
    op.drop_index("ix_grant_apps_funder_type", table_name="grant_applications")
    op.drop_table("grant_applications")
    op.drop_index("ix_org_profiles_user_legal_name", table_name="org_profiles")
    op.drop_table("org_profiles")
