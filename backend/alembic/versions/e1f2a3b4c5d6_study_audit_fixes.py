"""study audit fixes: mock exam pause + topic content_updated

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mock_exams",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mock_exams",
        sa.Column("paused_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mock_exams",
        sa.Column("remaining_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "learning_topics",
        sa.Column(
            "content_updated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("learning_topics", "content_updated")
    op.drop_column("mock_exams", "remaining_seconds")
    op.drop_column("mock_exams", "paused_seconds")
    op.drop_column("mock_exams", "paused_at")
