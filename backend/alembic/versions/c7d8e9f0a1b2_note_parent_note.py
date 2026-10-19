"""note hierarchy: child notes under a note

Revision ID: c7d8e9f0a1b2
Revises: e2f3a4b5c6d7
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 子笔记与父笔记在同一个分组内；父笔记被永久删除时子笔记提升到分组根级。
    op.add_column(
        "notes",
        sa.Column("parent_note_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_notes_parent_note_id",
        "notes",
        "notes",
        ["parent_note_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notes_kb_parent_sort",
        "notes",
        ["kb_id", "parent_note_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_notes_kb_parent_sort", table_name="notes")
    op.drop_constraint("fk_notes_parent_note_id", "notes", type_="foreignkey")
    op.drop_column("notes", "parent_note_id")
