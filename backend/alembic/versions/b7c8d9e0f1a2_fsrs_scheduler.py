"""FSRS-5 review scheduling state

Revision ID: b7c8d9e0f1a2
Revises: d2e3f4a5b6c7
Create Date: 2026-10-22 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FSRS-5 调度状态；旧字段 ease_factor / interval_days / repetitions 继续保留。
    op.add_column(
        "study_reviews",
        sa.Column("stability", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "study_reviews",
        sa.Column("difficulty", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "study_reviews",
        sa.Column("lapses", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "study_reviews",
        sa.Column(
            "review_state",
            sa.String(length=20),
            nullable=False,
            server_default="new",
        ),
    )
    op.add_column(
        "study_reviews",
        sa.Column("last_rating", sa.Integer(), nullable=True),
    )
    op.add_column(
        "study_reviews",
        sa.Column("fsrs_reps", sa.Integer(), nullable=False, server_default="0"),
    )

    # 旧 SM-2 数据回填：stability 取 interval（至少 1 天），difficulty 由 ease
    # 反推（ease 2.8 → 1，ease 1.3 → 10），有连续答对记录视为 review。
    op.execute(
        """
        UPDATE study_reviews
        SET stability = GREATEST(interval_days, 1.0),
            difficulty = LEAST(
                10.0,
                GREATEST(1.0, 1.0 + (2.8 - ease_factor) * 6.0)
            ),
            lapses = 0,
            review_state = CASE WHEN repetitions > 0 THEN 'review' ELSE 'new' END,
            last_rating = CASE
                WHEN last_correct IS TRUE THEN 3
                WHEN last_correct IS FALSE THEN 1
                ELSE NULL
            END,
            fsrs_reps = GREATEST(repetitions, 0)
        """
    )


def downgrade() -> None:
    op.drop_column("study_reviews", "fsrs_reps")
    op.drop_column("study_reviews", "last_rating")
    op.drop_column("study_reviews", "review_state")
    op.drop_column("study_reviews", "lapses")
    op.drop_column("study_reviews", "difficulty")
    op.drop_column("study_reviews", "stability")
