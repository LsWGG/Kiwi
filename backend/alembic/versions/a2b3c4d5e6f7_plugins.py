"""plugin / block registry

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="1.0.0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("author", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=40), nullable=False, server_default="puzzle"),
        sa.Column("homepage", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("key", name="uq_plugins_key"),
    )
    op.create_index("ix_plugins_enabled_key", "plugins", ["enabled", "key"])


def downgrade() -> None:
    op.drop_index("ix_plugins_enabled_key", table_name="plugins")
    op.drop_table("plugins")
