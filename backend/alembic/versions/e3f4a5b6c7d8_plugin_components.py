"""plugin component packages

Revision ID: e3f4a5b6c7d8
Revises: b5c6d7e8f9a0
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa

revision = "e3f4a5b6c7d8"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plugins",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="template"),
    )
    op.add_column(
        "plugins",
        sa.Column("entry", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "plugins",
        sa.Column("script", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "plugins",
        sa.Column("style", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("plugins", "style")
    op.drop_column("plugins", "script")
    op.drop_column("plugins", "entry")
    op.drop_column("plugins", "kind")
