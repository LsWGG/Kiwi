"""editor builtin extension toggles

Revision ID: b5c6d7e8f9a0
Revises: a2b3c4d5e6f7
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "editor_disabled_extensions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "editor_disabled_extensions")
