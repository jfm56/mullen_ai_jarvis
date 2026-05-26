"""Phase 8: backup_records.

Revision ID: 0009_phase8
Revises: 0008_phase5b
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_phase8"
down_revision: Union[str, None] = "0008_phase5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


KINDS = ("full", "schema_only", "data_only")
STATUSES = ("in_progress", "completed", "failed", "restored_from")


def upgrade() -> None:
    op.create_table(
        "backup_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False, server_default="full"),
        sa.Column("status", sa.String(32), nullable=False, server_default="in_progress"),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("encryption_alg", sa.String(32), nullable=False, server_default="AES-256-GCM"),
        sa.Column("key_id", sa.String(64), nullable=False, server_default="backup_master_key"),
        sa.Column("failure_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_backup_records_status", "backup_records", ["status"])
    op.create_index(
        "ix_backup_records_user_started", "backup_records", ["user_id", "started_at"]
    )
    op.create_check_constraint(
        "ck_backup_records_kind", "backup_records",
        "kind IN ('" + "','".join(KINDS) + "')",
    )
    op.create_check_constraint(
        "ck_backup_records_status", "backup_records",
        "status IN ('" + "','".join(STATUSES) + "')",
    )


def downgrade() -> None:
    op.drop_index("ix_backup_records_user_started", table_name="backup_records")
    op.drop_index("ix_backup_records_status", table_name="backup_records")
    op.drop_table("backup_records")
