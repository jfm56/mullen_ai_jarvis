"""Phase 5: projects, project_notes, opportunities, proposals.

Revision ID: 0005_phase5
Revises: 0004_phase4
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase5"
down_revision: Union[str, None] = "0004_phase4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROJECT_STATUSES = ("proposal", "active", "paused", "won", "lost", "archived")
VERTICALS = ("healthcare", "ems", "fire", "drone", "ai_consulting", "school", "other")
NOTE_KINDS = ("log", "decision", "risk", "blocker", "win")
OPP_KINDS = ("grant", "rfp", "partnership", "cold_inbound", "referral", "other")
OPP_STATUSES = (
    "watching", "researching", "applying", "submitted", "won", "lost", "dropped"
)
PROPOSAL_STATUSES = ("draft", "review", "submitted", "won", "lost", "discarded")


def upgrade() -> None:
    # ---- projects ----------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False, server_default="business"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("client", sa.String(255), nullable=False, server_default=""),
        sa.Column("vertical", sa.String(32), nullable=False, server_default="other"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("value_estimate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_date", sa.DateTime(timezone=True)),
        sa.Column("target_end_date", sa.DateTime(timezone=True)),
        sa.Column("actual_end_date", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_domain", "projects", ["domain"])
    op.create_index("ix_projects_vertical", "projects", ["vertical"])
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_projects_user_status", "projects", ["user_id", "status"])
    op.create_index(
        "ix_projects_user_slug", "projects", ["user_id", "slug"], unique=True
    )
    op.create_check_constraint(
        "ck_projects_status", "projects",
        "status IN ('" + "','".join(PROJECT_STATUSES) + "')",
    )
    op.create_check_constraint(
        "ck_projects_vertical", "projects",
        "vertical IN ('" + "','".join(VERTICALS) + "')",
    )

    # ---- project_notes -----------------------------------------------------
    op.create_table(
        "project_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False, server_default="log"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_project_notes_project_created", "project_notes", ["project_id", "created_at"]
    )
    op.create_check_constraint(
        "ck_project_notes_kind", "project_notes",
        "kind IN ('" + "','".join(NOTE_KINDS) + "')",
    )

    # ---- opportunities -----------------------------------------------------
    op.create_table(
        "opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False, server_default="business"),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("agency_or_company", sa.String(255), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False, server_default="other"),
        sa.Column("vertical", sa.String(32), nullable=False, server_default="other"),
        sa.Column("status", sa.String(32), nullable=False, server_default="watching"),
        sa.Column("url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("value_estimate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "source_email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_opportunities_kind", "opportunities", ["kind"])
    op.create_index("ix_opportunities_vertical", "opportunities", ["vertical"])
    op.create_index("ix_opportunities_status", "opportunities", ["status"])
    op.create_index("ix_opportunities_deadline", "opportunities", ["deadline"])
    op.create_index(
        "ix_opportunities_user_status", "opportunities", ["user_id", "status"]
    )
    op.create_index(
        "ix_opportunities_user_deadline", "opportunities", ["user_id", "deadline"]
    )
    op.create_check_constraint(
        "ck_opportunities_kind", "opportunities",
        "kind IN ('" + "','".join(OPP_KINDS) + "')",
    )
    op.create_check_constraint(
        "ck_opportunities_status", "opportunities",
        "status IN ('" + "','".join(OPP_STATUSES) + "')",
    )
    op.create_check_constraint(
        "ck_opportunities_vertical", "opportunities",
        "vertical IN ('" + "','".join(VERTICALS) + "')",
    )

    # ---- proposals ---------------------------------------------------------
    op.create_table(
        "proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "opportunity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("opportunities.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column(
            "generated_by", sa.String(64), nullable=False,
            server_default="business_development",
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "submit_approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_proposals_user_status", "proposals", ["user_id", "status"])
    op.create_check_constraint(
        "ck_proposals_status", "proposals",
        "status IN ('" + "','".join(PROPOSAL_STATUSES) + "')",
    )


def downgrade() -> None:
    op.drop_index("ix_proposals_user_status", table_name="proposals")
    op.drop_table("proposals")
    op.drop_index("ix_opportunities_user_deadline", table_name="opportunities")
    op.drop_index("ix_opportunities_user_status", table_name="opportunities")
    op.drop_index("ix_opportunities_deadline", table_name="opportunities")
    op.drop_index("ix_opportunities_status", table_name="opportunities")
    op.drop_index("ix_opportunities_vertical", table_name="opportunities")
    op.drop_index("ix_opportunities_kind", table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index("ix_project_notes_project_created", table_name="project_notes")
    op.drop_table("project_notes")
    op.drop_index("ix_projects_user_slug", table_name="projects")
    op.drop_index("ix_projects_user_status", table_name="projects")
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_index("ix_projects_vertical", table_name="projects")
    op.drop_index("ix_projects_domain", table_name="projects")
    op.drop_table("projects")
