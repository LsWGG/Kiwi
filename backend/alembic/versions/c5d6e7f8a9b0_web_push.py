"""web push subscriptions and reminder settings

Revision ID: c5d6e7f8a9b0
Revises: f4c5d6e7f8a9
Create Date: 2026-10-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "f4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
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
        sa.UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
    )

    op.add_column(
        "system_settings",
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "push_reminder_hour", sa.Integer(), nullable=False, server_default="20"
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "push_weekly_report", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column("push_last_daily_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column("push_last_weekly_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "push_vapid_private_key", sa.Text(), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "push_vapid_public_key",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "push_vapid_public_key")
    op.drop_column("system_settings", "push_vapid_private_key")
    op.drop_column("system_settings", "push_last_weekly_date")
    op.drop_column("system_settings", "push_last_daily_date")
    op.drop_column("system_settings", "push_weekly_report")
    op.drop_column("system_settings", "push_reminder_hour")
    op.drop_column("system_settings", "push_enabled")
    op.drop_table("push_subscriptions")
