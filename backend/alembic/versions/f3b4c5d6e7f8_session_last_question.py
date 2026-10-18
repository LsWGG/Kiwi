"""study sessions: remember the current unanswered question

Revision ID: f3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "study_sessions",
        sa.Column("last_question_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_study_sessions_last_question",
        "study_sessions",
        "study_questions",
        ["last_question_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_study_sessions_last_question", "study_sessions", type_="foreignkey"
    )
    op.drop_column("study_sessions", "last_question_id")
