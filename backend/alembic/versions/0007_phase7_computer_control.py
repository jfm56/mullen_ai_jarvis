"""Phase 7: allowed_apps, allowed_scripts, computer_action_log.

Revision ID: 0007_phase7
Revises: 0006_phase6
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase7"
down_revision: Union[str, None] = "0006_phase6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTION_TYPES = ("launch_app", "run_script", "file_search", "file_list", "file_read", "playwright_open")
ACTION_STATUSES = ("pending_approval", "executed", "failed", "blocked")


def upgrade() -> None:
    op.create_table(
        "allowed_apps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("args_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("hash_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expected_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_allowed_apps_user_name", "allowed_apps", ["user_id", "name"], unique=True
    )

    op.create_table(
        "allowed_scripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("interpreter", sa.String(255), nullable=False, server_default=""),
        sa.Column("args_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_allowed_scripts_user_name", "allowed_scripts", ["user_id", "name"], unique=True
    )

    op.create_table(
        "computer_action_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("args", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_approval"),
        sa.Column("return_code", sa.Integer()),
        sa.Column("stdout_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("stderr_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("blocked_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_computer_action_log_action_type", "computer_action_log", ["action_type"])
    op.create_index("ix_computer_action_log_status", "computer_action_log", ["status"])
    op.create_index("ix_computer_action_log_started_at", "computer_action_log", ["started_at"])
    op.create_index(
        "ix_computer_action_log_user_started",
        "computer_action_log",
        ["user_id", "started_at"],
    )
    op.create_check_constraint(
        "ck_computer_action_log_action_type", "computer_action_log",
        "action_type IN ('" + "','".join(ACTION_TYPES) + "')",
    )
    op.create_check_constraint(
        "ck_computer_action_log_status", "computer_action_log",
        "status IN ('" + "','".join(ACTION_STATUSES) + "')",
    )


def downgrade() -> None:
    op.drop_index("ix_computer_action_log_user_started", table_name="computer_action_log")
    op.drop_index("ix_computer_action_log_started_at", table_name="computer_action_log")
    op.drop_index("ix_computer_action_log_status", table_name="computer_action_log")
    op.drop_index("ix_computer_action_log_action_type", table_name="computer_action_log")
    op.drop_table("computer_action_log")
    op.drop_index("ix_allowed_scripts_user_name", table_name="allowed_scripts")
    op.drop_table("allowed_scripts")
    op.drop_index("ix_allowed_apps_user_name", table_name="allowed_apps")
    op.drop_table("allowed_apps")
