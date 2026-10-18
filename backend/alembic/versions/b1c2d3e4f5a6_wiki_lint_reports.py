"""persist Wiki health-check reports

Revision ID: b1c2d3e4f5a6
Revises: a4b5c6d7e8f9
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wiki_lint_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("trigger", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column(
            "semantic_status",
            sa.String(length=20),
            nullable=False,
            server_default="skipped",
        ),
        sa.Column("semantic_error", sa.Text(), nullable=True),
        sa.Column(
            "summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "issues_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
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
        sa.ForeignKeyConstraint(
            ["kb_id"], ["knowledge_bases.id"], name="fk_wiki_lint_reports_kb", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_wiki_lint_reports_kb_id", "wiki_lint_reports", ["kb_id"])
    op.create_index(
        "ix_wiki_lint_reports_kb_generated",
        "wiki_lint_reports",
        ["kb_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_wiki_lint_reports_kb_generated", table_name="wiki_lint_reports")
    op.drop_index("ix_wiki_lint_reports_kb_id", table_name="wiki_lint_reports")
    op.drop_table("wiki_lint_reports")
