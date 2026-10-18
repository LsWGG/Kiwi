"""study sessions: scope drill to a single wiki topic

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "study_sessions",
        sa.Column("topic_slug", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("study_sessions", "topic_slug")
