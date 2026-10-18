"""builtin demo knowledge base

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("is_builtin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("knowledge_bases", sa.Column("builtin_key", sa.String(64), nullable=True))
    op.create_index(
        "ix_knowledge_bases_builtin_key", "knowledge_bases", ["builtin_key"], unique=True
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "deleted_at")
    op.drop_index("ix_knowledge_bases_builtin_key", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "builtin_key")
    op.drop_column("knowledge_bases", "is_builtin")
