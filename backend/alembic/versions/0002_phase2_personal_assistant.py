"""Phase 2: tasks, reminders, calendar_events, oauth_accounts.

Revision ID: 0002_phase2
Revises: 0001_initial
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase2"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TASK_STATUSES = ("pending", "in_progress", "done", "cancelled")
TASK_PRIORITIES = ("low", "normal", "high", "urgent")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False, server_default="personal"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tasks_domain", "tasks", ["domain"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"])
    op.create_index("ix_tasks_user_due", "tasks", ["user_id", "due_at"])
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('" + "','".join(TASK_STATUSES) + "')",
    )
    op.create_check_constraint(
        "ck_tasks_priority",
        "tasks",
        "priority IN ('" + "','".join(TASK_PRIORITIES) + "')",
    )

    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False, server_default="personal"),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fired_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reminders_fire_at", "reminders", ["fire_at"])
    op.create_index(
        "ix_reminders_due_unfired",
        "reminders",
        ["fire_at", "fired", "cancelled"],
    )

    op.create_table(
        "calendar_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False, server_default="personal"),
        sa.Column("source", sa.String(32), nullable=False, server_default="google"),
        sa.Column("external_id", sa.String(255)),
        sa.Column("calendar_id", sa.String(255), nullable=False, server_default="primary"),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("location", sa.String(512), nullable=False, server_default=""),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_calendar_events_domain", "calendar_events", ["domain"])
    op.create_index("ix_calendar_events_start_at", "calendar_events", ["start_at"])
    op.create_index(
        "ix_calendar_events_user_start", "calendar_events", ["user_id", "start_at"]
    )
    op.create_index(
        "ix_calendar_events_source_external",
        "calendar_events",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "oauth_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_email", sa.String(255), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_oauth_provider_account",
        "oauth_accounts",
        ["user_id", "provider", "account_email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_provider_account", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")

    op.drop_index("ix_calendar_events_source_external", table_name="calendar_events")
    op.drop_index("ix_calendar_events_user_start", table_name="calendar_events")
    op.drop_index("ix_calendar_events_start_at", table_name="calendar_events")
    op.drop_index("ix_calendar_events_domain", table_name="calendar_events")
    op.drop_table("calendar_events")

    op.drop_index("ix_reminders_due_unfired", table_name="reminders")
    op.drop_index("ix_reminders_fire_at", table_name="reminders")
    op.drop_table("reminders")

    op.drop_index("ix_tasks_user_due", table_name="tasks")
    op.drop_index("ix_tasks_user_status", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_domain", table_name="tasks")
    op.drop_table("tasks")
