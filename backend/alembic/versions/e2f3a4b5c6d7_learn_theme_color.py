"""learn mode brand color

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 编辑 / 学习两套主题色分别保存；老数据沿用学习模式原有的青绿色。
    op.add_column(
        "system_settings",
        sa.Column(
            "learn_theme_color",
            sa.String(length=20),
            nullable=False,
            server_default="#10b981",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "learn_theme_color")
