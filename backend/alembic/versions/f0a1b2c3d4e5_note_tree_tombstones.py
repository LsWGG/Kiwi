"""note tree tombstones for incremental refresh

Revision ID: f0a1b2c3d4e5
Revises: c5d6e7f8a9b0
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_tree_tombstones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=10), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
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
    op.create_index(
        "ix_note_tree_tombstones_kb_id",
        "note_tree_tombstones",
        ["kb_id"],
    )
    op.create_index(
        "ix_note_tree_tombstones_kb_created",
        "note_tree_tombstones",
        ["kb_id", "created_at"],
    )
    op.create_index(
        "ix_note_tree_tombstones_item",
        "note_tree_tombstones",
        ["kb_id", "item_type", "item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_note_tree_tombstones_item", table_name="note_tree_tombstones")
    op.drop_index(
        "ix_note_tree_tombstones_kb_created", table_name="note_tree_tombstones"
    )
    op.drop_index("ix_note_tree_tombstones_kb_id", table_name="note_tree_tombstones")
    op.drop_table("note_tree_tombstones")
