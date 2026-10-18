"""notes: allow canvas kind

Revision ID: b8d4f2a6c1e9
Revises: a7c2e9f1b3d4
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d4f2a6c1e9"
down_revision: str | None = "a7c2e9f1b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('doc', 'database', 'link', 'import', 'canvas')"
_OLD_KINDS = "kind IN ('doc', 'database', 'link', 'import')"


def upgrade() -> None:
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.create_check_constraint("ck_notes_kind", "notes", _KINDS)


def downgrade() -> None:
    op.execute("UPDATE notes SET kind = 'doc' WHERE kind = 'canvas'")
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.create_check_constraint("ck_notes_kind", "notes", _OLD_KINDS)
