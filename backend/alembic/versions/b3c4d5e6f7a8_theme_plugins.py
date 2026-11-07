"""theme plugins and active theme settings

Revision ID: b3c4d5e6f7a8
Revises: f1a2b3c4d5e6
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b3c4d5e6f7a8"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("active_theme", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "theme_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "plugin_assets",
        sa.Column("plugin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=100),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plugin_id", "path"),
    )


def downgrade() -> None:
    op.drop_table("plugin_assets")
    op.drop_column("system_settings", "theme_overrides")
    op.drop_column("system_settings", "active_theme")
