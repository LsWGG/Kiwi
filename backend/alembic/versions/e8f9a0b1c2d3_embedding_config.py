"""embedding runtime config

Revision ID: e8f9a0b1c2d3
Revises: c4d5e6f7a8b9
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="local"),
        sa.Column("api_base", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("api_model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("api_timeout", sa.Float(), nullable=False, server_default="60"),
        sa.Column("api_batch_size", sa.Integer(), nullable=False, server_default="64"),
        sa.Column("api_concurrency", sa.Integer(), nullable=False, server_default="4"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("embedding_config")
