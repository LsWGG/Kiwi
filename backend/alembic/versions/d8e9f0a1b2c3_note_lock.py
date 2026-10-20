"""note lock: password hash, salt, hint and lock time

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 密码锁：只存 PBKDF2 哈希与盐，正文通过 X-Note-Token 解锁后返回。
    op.add_column("notes", sa.Column("lock_hash", sa.String(length=255), nullable=True))
    op.add_column("notes", sa.Column("lock_salt", sa.String(length=64), nullable=True))
    op.add_column("notes", sa.Column("lock_hint", sa.String(length=120), nullable=True))
    op.add_column(
        "notes",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notes_lock_hash", "notes", ["lock_hash"])


def downgrade() -> None:
    op.drop_index("ix_notes_lock_hash", table_name="notes")
    op.drop_column("notes", "locked_at")
    op.drop_column("notes", "lock_hint")
    op.drop_column("notes", "lock_salt")
    op.drop_column("notes", "lock_hash")
