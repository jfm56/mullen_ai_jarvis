"""Phase 3: memories + topic_disables, with pgvector extension.

Revision ID: 0003_phase3
Revises: 0002_phase2
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision: str = "0003_phase3"
down_revision: Union[str, None] = "0002_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MEMORY_KINDS = ("short_term", "episodic", "semantic", "procedural")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    dim = get_settings().embedding_dim

    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim)),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "source_approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "source_audit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audit_log.id", ondelete="SET NULL"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_memories_domain", "memories", ["domain"])
    op.create_index("ix_memories_kind", "memories", ["kind"])
    op.create_index(
        "ix_memories_user_domain_kind", "memories", ["user_id", "domain", "kind"]
    )
    op.create_index(
        "ix_memories_user_domain_live",
        "memories",
        ["user_id", "domain", "deleted_at"],
    )
    op.create_check_constraint(
        "ck_memories_kind",
        "memories",
        "kind IN ('" + "','".join(MEMORY_KINDS) + "')",
    )

    # Vector similarity index. ivfflat needs `lists` tuned to row count;
    # 100 is fine for the early single-user dataset and can be reindexed later.
    op.execute(
        "CREATE INDEX ix_memories_embedding ON memories "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
    )

    op.create_table(
        "topic_disables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("pattern", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_topic_disables_user_domain", "topic_disables", ["user_id", "domain"]
    )


def downgrade() -> None:
    op.drop_index("ix_topic_disables_user_domain", table_name="topic_disables")
    op.drop_table("topic_disables")

    op.execute("DROP INDEX IF EXISTS ix_memories_embedding;")
    op.drop_index("ix_memories_user_domain_live", table_name="memories")
    op.drop_index("ix_memories_user_domain_kind", table_name="memories")
    op.drop_index("ix_memories_kind", table_name="memories")
    op.drop_index("ix_memories_domain", table_name="memories")
    op.drop_table("memories")
    # Leave the vector extension installed — other migrations may depend on it.
