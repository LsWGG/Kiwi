"""learn mode logo and description

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 学习模式拥有独立的 Logo 与一句话描述，表单按模式回显；留空沿用品牌 Logo。
    op.add_column(
        "system_settings",
        sa.Column(
            "learn_logo_url",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "learn_description",
            sa.Text(),
            nullable=False,
            server_default="学习训练 · 复习",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "learn_description")
    op.drop_column("system_settings", "learn_logo_url")
