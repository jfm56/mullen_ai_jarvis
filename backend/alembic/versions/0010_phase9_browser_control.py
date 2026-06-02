"""Phase 9: browser_allowed_domains, browser_sessions, browser_actions.

Layered on top of Phase 7 Computer Control safety primitives. Adds
Playwright session management + per-domain allow-listing.

Revision ID: 0010_phase9
Revises: 0009_phase8
Create Date: 2026-05-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_phase9"
down_revision: Union[str, None] = "0009_phase8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SESSION_STATUSES = ("starting", "active", "idle", "closed", "crashed")
ACTION_TYPES = (
    "navigate", "screenshot", "get_text", "click", "type_text",
    "submit", "wait", "stop",
)
ACTION_STATUSES = ("pending_approval", "executed", "blocked", "failed")


def upgrade() -> None:
    op.create_table(
        "browser_allowed_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pattern", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "allow_form_submit", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_browser_domains_user_pattern",
        "browser_allowed_domains",
        ["user_id", "pattern"],
        unique=True,
    )

    op.create_table(
        "browser_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(128), nullable=False, server_default=""),
        sa.Column("profile_dir", sa.String(1024), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="starting"),
        sa.Column("current_url", sa.String(2048), nullable=False, server_default=""),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_browser_sessions_status", "browser_sessions", ["status"]
    )
    op.create_index(
        "ix_browser_sessions_user_status",
        "browser_sessions",
        ["user_id", "status"],
    )
    op.create_check_constraint(
        "ck_browser_sessions_status",
        "browser_sessions",
        "status IN ('" + "','".join(SESSION_STATUSES) + "')",
    )

    op.create_table(
        "browser_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("browser_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("target", sa.Text(), nullable=False, server_default=""),
        sa.Column("args", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_approval"),
        sa.Column("blocked_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("result_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_browser_actions_action_type", "browser_actions", ["action_type"]
    )
    op.create_index(
        "ix_browser_actions_status", "browser_actions", ["status"]
    )
    op.create_index(
        "ix_browser_actions_started_at", "browser_actions", ["started_at"]
    )
    op.create_index(
        "ix_browser_actions_session_started",
        "browser_actions",
        ["session_id", "started_at"],
    )
    op.create_check_constraint(
        "ck_browser_actions_type", "browser_actions",
        "action_type IN ('" + "','".join(ACTION_TYPES) + "')",
    )
    op.create_check_constraint(
        "ck_browser_actions_status", "browser_actions",
        "status IN ('" + "','".join(ACTION_STATUSES) + "')",
    )


def downgrade() -> None:
    op.drop_index("ix_browser_actions_session_started", table_name="browser_actions")
    op.drop_index("ix_browser_actions_started_at", table_name="browser_actions")
    op.drop_index("ix_browser_actions_status", table_name="browser_actions")
    op.drop_index("ix_browser_actions_action_type", table_name="browser_actions")
    op.drop_table("browser_actions")

    op.drop_index("ix_browser_sessions_user_status", table_name="browser_sessions")
    op.drop_index("ix_browser_sessions_status", table_name="browser_sessions")
    op.drop_table("browser_sessions")

    op.drop_index("ix_browser_domains_user_pattern", table_name="browser_allowed_domains")
    op.drop_table("browser_allowed_domains")
