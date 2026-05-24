"""Initial security spine: users, approvals, audit_log (append-only).

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "executed", "failed")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("action_class", sa.String(64), nullable=False),
        sa.Column("action_name", sa.String(128), nullable=False),
        sa.Column("target_summary", sa.Text(), nullable=False),
        sa.Column("preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
    )
    op.create_index("ix_approvals_created_at", "approvals", ["created_at"])
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_index("ix_approvals_agent", "approvals", ["agent"])
    op.create_index("ix_approvals_domain", "approvals", ["domain"])
    op.create_check_constraint(
        "ck_approvals_status",
        "approvals",
        "status IN ('" + "','".join(APPROVAL_STATUSES) + "')",
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("action_class", sa.String(64), nullable=False),
        sa.Column("action_name", sa.String(128), nullable=False),
        sa.Column("target_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("integration", sa.String(64), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_hash", sa.String(32), nullable=False, server_default=""),
        sa.Column("output_hash", sa.String(32), nullable=False, server_default=""),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_agent", "audit_log", ["agent"])
    op.create_index("ix_audit_log_domain", "audit_log", ["domain"])
    op.create_index("ix_audit_log_agent_ts", "audit_log", ["agent", "timestamp"])
    op.create_index("ix_audit_log_domain_ts", "audit_log", ["domain", "timestamp"])

    # --- Append-only enforcement -------------------------------------------------
    # Block UPDATE and DELETE on audit_log at the DB level. The application code
    # could be tricked or have a bug; the trigger is a backstop the agents can't
    # override even with their full credentials.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_block_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_block_mutation();")
    op.drop_index("ix_audit_log_domain_ts", table_name="audit_log")
    op.drop_index("ix_audit_log_agent_ts", table_name="audit_log")
    op.drop_index("ix_audit_log_domain", table_name="audit_log")
    op.drop_index("ix_audit_log_agent", table_name="audit_log")
    op.drop_index("ix_audit_log_timestamp", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_approvals_domain", table_name="approvals")
    op.drop_index("ix_approvals_agent", table_name="approvals")
    op.drop_index("ix_approvals_status", table_name="approvals")
    op.drop_index("ix_approvals_created_at", table_name="approvals")
    op.drop_table("approvals")
    op.drop_table("users")
