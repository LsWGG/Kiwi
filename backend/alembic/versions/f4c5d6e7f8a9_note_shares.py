"""note read-only share links

Revision ID: f4c5d6e7f8a9
Revises: b7c8d9e0f1a2
Create Date: 2026-10-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f4c5d6e7f8a9"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=True),
        sa.Column("password_salt", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_note_shares_kb_id", "note_shares", ["kb_id"])
    op.create_index("ix_note_shares_note_id", "note_shares", ["note_id"])
    op.create_index("ix_note_shares_note", "note_shares", ["note_id", "created_at"])
    op.create_index("ix_note_shares_token", "note_shares", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_note_shares_token", table_name="note_shares")
    op.drop_index("ix_note_shares_note", table_name="note_shares")
    op.drop_index("ix_note_shares_note_id", table_name="note_shares")
    op.drop_index("ix_note_shares_kb_id", table_name="note_shares")
    op.drop_table("note_shares")
