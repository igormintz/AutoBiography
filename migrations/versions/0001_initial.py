"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("short_id", sa.String(length=12), nullable=False, unique=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="voice"),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "entities",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "follow_up_questions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("approx_age", sa.Integer(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ok", index=True),
        sa.Column("drive_json_id", sa.String(length=200), nullable=True),
        sa.Column("drive_text_id", sa.String(length=200), nullable=True),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_entries_tags_gin", "entries", ["tags"], postgresql_using="gin")
    op.create_index("ix_entries_entities_gin", "entries", ["entities"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_entries_transcript_trgm ON entries USING gin (transcript gin_trgm_ops)"
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("seconds", sa.Numeric(10, 3), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_index("ix_entries_transcript_trgm", table_name="entries")
    op.drop_index("ix_entries_entities_gin", table_name="entries")
    op.drop_index("ix_entries_tags_gin", table_name="entries")
    op.drop_table("entries")
