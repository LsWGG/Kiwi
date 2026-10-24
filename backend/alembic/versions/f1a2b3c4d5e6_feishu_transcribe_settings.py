"""feishu minutes transcription settings

Revision ID: f1a2b3c4d5e6
Revises: e3f4a5b6c7d8
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "transcribe_provider",
            sa.String(length=20),
            nullable=False,
            server_default="auto",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "feishu_app_id", sa.String(length=100), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "feishu_app_secret_encrypted",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "feishu_user_token_encrypted",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "feishu_refresh_token_encrypted",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "feishu_folder_token",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "feishu_redirect_uri",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "feishu_redirect_uri")
    op.drop_column("system_settings", "feishu_folder_token")
    op.drop_column("system_settings", "feishu_refresh_token_encrypted")
    op.drop_column("system_settings", "feishu_user_token_encrypted")
    op.drop_column("system_settings", "feishu_app_secret_encrypted")
    op.drop_column("system_settings", "feishu_app_id")
    op.drop_column("system_settings", "transcribe_provider")
