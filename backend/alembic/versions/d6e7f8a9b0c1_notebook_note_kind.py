"""notes: allow notebook kind

Revision ID: d6e7f8a9b0c1
Revises: b1c2d3e4f5a6
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('doc', 'database', 'link', 'import', 'canvas', 'notebook')"
_OLD_KINDS = "kind IN ('doc', 'database', 'link', 'import', 'canvas')"


def upgrade() -> None:
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.create_check_constraint("ck_notes_kind", "notes", _KINDS)


def downgrade() -> None:
    op.execute("UPDATE notes SET kind = 'doc' WHERE kind = 'notebook'")
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.create_check_constraint("ck_notes_kind", "notes", _OLD_KINDS)
