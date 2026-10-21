"""notes: allow sheet kind

Revision ID: c1d2e3f4a5b6
Revises: b7c1d2e3f4a5
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b7c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('doc', 'database', 'link', 'import', 'canvas', 'notebook', 'sheet')"
_OLD_KINDS = "kind IN ('doc', 'database', 'link', 'import', 'canvas', 'notebook')"


def upgrade() -> None:
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.create_check_constraint("ck_notes_kind", "notes", _KINDS)


def downgrade() -> None:
    op.execute("UPDATE notes SET kind = 'doc' WHERE kind = 'sheet'")
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.create_check_constraint("ck_notes_kind", "notes", _OLD_KINDS)
