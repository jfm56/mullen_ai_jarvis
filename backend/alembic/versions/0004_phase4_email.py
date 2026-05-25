"""Phase 4: emails + email_drafts.

Revision ID: 0004_phase4
Revises: 0003_phase3
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase4"
down_revision: Union[str, None] = "0003_phase3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


EMAIL_CATEGORIES = (
    "unclassified",
    "urgent",
    "waiting_on_me",
    "fyi",
    "newsletter",
    "suspicious",
    "lead_inquiry",
    "internal",
    "personal",
)
EMAIL_DIRECTIONS = ("inbound", "outbound")


def upgrade() -> None:
    op.create_table(
        "emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False, server_default="personal"),
        sa.Column("source", sa.String(32), nullable=False, server_default="gmail"),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("thread_id", sa.String(255)),
        sa.Column("direction", sa.String(16), nullable=False, server_default="inbound"),
        sa.Column("from_addr", sa.String(512), nullable=False, server_default=""),
        sa.Column("to_addrs", sa.Text(), nullable=False, server_default=""),
        sa.Column("cc_addrs", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.String(1024), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("category", sa.String(32), nullable=False, server_default="unclassified"),
        sa.Column("urgency_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_scam", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scam_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("scam_signals", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_emails_domain", "emails", ["domain"])
    op.create_index("ix_emails_thread_id", "emails", ["thread_id"])
    op.create_index("ix_emails_received_at", "emails", ["received_at"])
    op.create_index("ix_emails_category", "emails", ["category"])
    op.create_index("ix_emails_is_scam", "emails", ["is_scam"])
    op.create_index(
        "ix_emails_source_external", "emails", ["source", "external_id"], unique=True
    )
    op.create_index("ix_emails_user_received", "emails", ["user_id", "received_at"])
    op.create_index("ix_emails_user_category", "emails", ["user_id", "category"])
    op.create_check_constraint(
        "ck_emails_category",
        "emails",
        "category IN ('" + "','".join(EMAIL_CATEGORIES) + "')",
    )
    op.create_check_constraint(
        "ck_emails_direction",
        "emails",
        "direction IN ('" + "','".join(EMAIL_DIRECTIONS) + "')",
    )

    op.create_table(
        "email_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
        ),
        sa.Column("to_addrs", sa.Text(), nullable=False, server_default=""),
        sa.Column("cc_addrs", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.String(1024), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column(
            "generated_by", sa.String(64), nullable=False, server_default="email_assistant"
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "sent_approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("discarded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_email_drafts_user_email", "email_drafts", ["user_id", "email_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_email_drafts_user_email", table_name="email_drafts")
    op.drop_table("email_drafts")
    op.drop_index("ix_emails_user_category", table_name="emails")
    op.drop_index("ix_emails_user_received", table_name="emails")
    op.drop_index("ix_emails_source_external", table_name="emails")
    op.drop_index("ix_emails_is_scam", table_name="emails")
    op.drop_index("ix_emails_category", table_name="emails")
    op.drop_index("ix_emails_received_at", table_name="emails")
    op.drop_index("ix_emails_thread_id", table_name="emails")
    op.drop_index("ix_emails_domain", table_name="emails")
    op.drop_table("emails")
