"""notes workspace: kinds, folders ordering, databases, attachments

Revision ID: a7c2e9f1b3d4
Revises: f3a9c1d2e4b5
Create Date: 2026-10-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c2e9f1b3d4"
down_revision: Union[str, None] = "f3a9c1d2e4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- notes：升级为统一工作区节点 ----
    op.add_column(
        "notes",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="doc"),
    )
    op.add_column(
        "notes",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notes",
        sa.Column(
            "props_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_notes_kind", "notes", "kind IN ('doc', 'database', 'link', 'import')"
    )
    op.create_index("ix_notes_kb_kind", "notes", ["kb_id", "kind"], unique=False)
    op.create_index(
        "ix_notes_kb_folder_sort", "notes", ["kb_id", "folder_id", "sort_order"], unique=False
    )

    # ---- note_collections：绑定数据表笔记 ----
    op.add_column("note_collections", sa.Column("note_id", sa.Uuid(), nullable=True))
    op.add_column(
        "note_collections",
        sa.Column(
            "views_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_note_collections_note_id",
        "note_collections",
        "notes",
        ["note_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_note_collections_note_id", "note_collections", ["note_id"]
    )

    # ---- collection_rows ----
    op.create_table(
        "collection_rows",
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["note_collections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collection_rows_kb_id", "collection_rows", ["kb_id"], unique=False
    )
    op.create_index(
        "ix_collection_rows_collection_id",
        "collection_rows",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_rows_collection_sort",
        "collection_rows",
        ["collection_id", "sort_order"],
        unique=False,
    )

    # ---- note_attachments ----
    op.create_table(
        "note_attachments",
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_note_attachments_kb_id", "note_attachments", ["kb_id"], unique=False
    )
    op.create_index(
        "ix_note_attachments_note_id", "note_attachments", ["note_id"], unique=False
    )

    # ---- ingest_jobs：关联工作区导入笔记 ----
    op.add_column("ingest_jobs", sa.Column("note_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_ingest_jobs_note_id",
        "ingest_jobs",
        "notes",
        ["note_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_ingest_jobs_note_id", "ingest_jobs", ["note_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_note_id", table_name="ingest_jobs")
    op.drop_constraint("fk_ingest_jobs_note_id", "ingest_jobs", type_="foreignkey")
    op.drop_column("ingest_jobs", "note_id")

    op.drop_index("ix_note_attachments_note_id", table_name="note_attachments")
    op.drop_index("ix_note_attachments_kb_id", table_name="note_attachments")
    op.drop_table("note_attachments")

    op.drop_index("ix_collection_rows_collection_sort", table_name="collection_rows")
    op.drop_index("ix_collection_rows_collection_id", table_name="collection_rows")
    op.drop_index("ix_collection_rows_kb_id", table_name="collection_rows")
    op.drop_table("collection_rows")

    op.drop_constraint(
        "uq_note_collections_note_id", "note_collections", type_="unique"
    )
    op.drop_constraint(
        "fk_note_collections_note_id", "note_collections", type_="foreignkey"
    )
    op.drop_column("note_collections", "views_json")
    op.drop_column("note_collections", "note_id")

    op.drop_index("ix_notes_kb_folder_sort", table_name="notes")
    op.drop_index("ix_notes_kb_kind", table_name="notes")
    op.drop_constraint("ck_notes_kind", "notes", type_="check")
    op.drop_column("notes", "props_json")
    op.drop_column("notes", "sort_order")
    op.drop_column("notes", "kind")
