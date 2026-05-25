"""Phase 6: social_posts, leads, outreach_messages.

Revision ID: 0006_phase6
Revises: 0005_phase5
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_phase6"
down_revision: Union[str, None] = "0005_phase5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PLATFORMS = ("linkedin", "facebook", "x", "instagram", "blog", "other")
POST_STATUSES = ("draft", "scheduled", "published", "discarded")
VERTICALS = ("healthcare", "ems", "fire", "drone", "ai_consulting", "school", "other")
LEAD_SOURCES = ("manual", "inbound_email", "referral", "event", "research", "other")
LEAD_STATUSES = (
    "researched", "contacted", "meeting", "proposal", "won", "lost", "disqualified"
)
CHANNELS = ("email", "linkedin", "phone", "sms", "other")
OUTREACH_STATUSES = ("draft", "sent", "replied", "discarded")


def upgrade() -> None:
    op.create_table(
        "social_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(32), nullable=False, server_default="linkedin"),
        sa.Column("vertical", sa.String(32), nullable=False, server_default="other"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "post_approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("engagement", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "generated_by", sa.String(64), nullable=False, server_default="marketing"
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_social_posts_platform", "social_posts", ["platform"])
    op.create_index("ix_social_posts_vertical", "social_posts", ["vertical"])
    op.create_index("ix_social_posts_status", "social_posts", ["status"])
    op.create_index("ix_social_posts_user_status", "social_posts", ["user_id", "status"])
    op.create_index(
        "ix_social_posts_user_scheduled", "social_posts", ["user_id", "scheduled_for"]
    )
    op.create_check_constraint(
        "ck_social_posts_platform", "social_posts",
        "platform IN ('" + "','".join(PLATFORMS) + "')",
    )
    op.create_check_constraint(
        "ck_social_posts_status", "social_posts",
        "status IN ('" + "','".join(POST_STATUSES) + "')",
    )
    op.create_check_constraint(
        "ck_social_posts_vertical", "social_posts",
        "vertical IN ('" + "','".join(VERTICALS) + "')",
    )

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("company", sa.String(255), nullable=False, server_default=""),
        sa.Column("role", sa.String(255), nullable=False, server_default=""),
        sa.Column("email", sa.String(512), nullable=False, server_default=""),
        sa.Column("phone", sa.String(64), nullable=False, server_default=""),
        sa.Column("vertical", sa.String(32), nullable=False, server_default="other"),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(32), nullable=False, server_default="researched"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "source_email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
        ),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True)),
        sa.Column("next_followup_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_leads_vertical", "leads", ["vertical"])
    op.create_index("ix_leads_status", "leads", ["status"])
    op.create_index("ix_leads_next_followup_at", "leads", ["next_followup_at"])
    op.create_index("ix_leads_user_status", "leads", ["user_id", "status"])
    op.create_index("ix_leads_user_followup", "leads", ["user_id", "next_followup_at"])
    op.create_check_constraint(
        "ck_leads_source", "leads",
        "source IN ('" + "','".join(LEAD_SOURCES) + "')",
    )
    op.create_check_constraint(
        "ck_leads_status", "leads",
        "status IN ('" + "','".join(LEAD_STATUSES) + "')",
    )
    op.create_check_constraint(
        "ck_leads_vertical", "leads",
        "vertical IN ('" + "','".join(VERTICALS) + "')",
    )
    op.create_check_constraint(
        "ck_leads_score_range", "leads", "score >= 0 AND score <= 100"
    )

    op.create_table(
        "outreach_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(16), nullable=False, server_default="email"),
        sa.Column("subject", sa.String(1024), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column(
            "sent_approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "generated_by", sa.String(64), nullable=False, server_default="lead_generation"
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_outreach_lead_created", "outreach_messages", ["lead_id", "created_at"]
    )
    op.create_check_constraint(
        "ck_outreach_channel", "outreach_messages",
        "channel IN ('" + "','".join(CHANNELS) + "')",
    )
    op.create_check_constraint(
        "ck_outreach_status", "outreach_messages",
        "status IN ('" + "','".join(OUTREACH_STATUSES) + "')",
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_lead_created", table_name="outreach_messages")
    op.drop_table("outreach_messages")

    op.drop_index("ix_leads_user_followup", table_name="leads")
    op.drop_index("ix_leads_user_status", table_name="leads")
    op.drop_index("ix_leads_next_followup_at", table_name="leads")
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_vertical", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_social_posts_user_scheduled", table_name="social_posts")
    op.drop_index("ix_social_posts_user_status", table_name="social_posts")
    op.drop_index("ix_social_posts_status", table_name="social_posts")
    op.drop_index("ix_social_posts_vertical", table_name="social_posts")
    op.drop_index("ix_social_posts_platform", table_name="social_posts")
    op.drop_table("social_posts")
