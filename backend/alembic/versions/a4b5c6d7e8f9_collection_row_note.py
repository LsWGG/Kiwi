"""collection rows linked to full notes

Revision ID: a4b5c6d7e8f9
Revises: f3b4c5d6e7f8
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "collection_rows",
        sa.Column("note_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_collection_rows_note",
        "collection_rows",
        "notes",
        ["note_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_collection_rows_note_id",
        "collection_rows",
        ["note_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_collection_rows_note_id", table_name="collection_rows")
    op.drop_constraint(
        "fk_collection_rows_note", "collection_rows", type_="foreignkey"
    )
    op.drop_column("collection_rows", "note_id")
