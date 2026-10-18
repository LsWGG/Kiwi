"""import: sources metadata + import_batches

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "parse_engine", sa.String(length=40), nullable=False, server_default="native"
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "quality_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "scan_status",
            sa.String(length=20),
            nullable=False,
            server_default="unavailable",
        ),
    )
    op.add_column(
        "sources",
        sa.Column("scan_detail", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "sources", sa.Column("external_id", sa.String(length=300), nullable=True)
    )
    op.add_column(
        "sources", sa.Column("source_url", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "sources",
        sa.Column("content_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sources_kb_external", "sources", ["kb_id", "external_id"]
    )

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider", sa.String(length=20), nullable=False, server_default="upload"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="running"
        ),
        sa.Column("total_sources", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "report_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_kb_id", "import_batches", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_import_batches_kb_id", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_index("ix_sources_kb_external", table_name="sources")
    op.drop_column("sources", "content_updated_at")
    op.drop_column("sources", "source_url")
    op.drop_column("sources", "external_id")
    op.drop_column("sources", "scan_detail")
    op.drop_column("sources", "scan_status")
    op.drop_column("sources", "quality_report")
    op.drop_column("sources", "parse_engine")
