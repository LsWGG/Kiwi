"""note revisions, system settings, todo mirrors and kb schedules

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 知识库排序与定时任务 ---
    op.add_column(
        "knowledge_bases",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "wiki_compile_interval_hours",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("wiki_compile_last_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "wiki_compile_last_status",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "todo_sync_interval_hours", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("todo_sync_last_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- 笔记历史版本 ---
    op.create_table(
        "note_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("body_md", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "props_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="auto"),
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
    op.create_index("ix_note_revisions_kb_id", "note_revisions", ["kb_id"])
    op.create_index("ix_note_revisions_note_id", "note_revisions", ["note_id"])
    op.create_index(
        "ix_note_revisions_note_created", "note_revisions", ["note_id", "created_at"]
    )

    # --- 系统设置（单行） ---
    op.create_table(
        "system_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("app_name", sa.String(length=100), nullable=False, server_default="Kiwi"),
        sa.Column(
            "app_description",
            sa.Text(),
            nullable=False,
            server_default="知识编译与检索系统",
        ),
        sa.Column("logo_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column(
            "theme_color", sa.String(length=20), nullable=False, server_default="#5a55c7"
        ),
        sa.Column(
            "ocr_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "ocr_provider", sa.String(length=40), nullable=False, server_default="openai"
        ),
        sa.Column("ocr_api_base", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("ocr_api_model", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("ocr_encrypted_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "ocr_timeout", sa.Float(), nullable=False, server_default="120"
        ),
        sa.Column(
            "ocr_language", sa.String(length=40), nullable=False, server_default="auto"
        ),
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

    # --- 待办镜像 ---
    op.create_table(
        "todo_mirrors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "hub_note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_note_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=20), nullable=False),
        sa.Column("source_ref", sa.String(length=120), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "kb_id",
            "source_note_id",
            "source_kind",
            "source_ref",
            name="uq_todo_mirror_source",
        ),
    )
    op.create_index("ix_todo_mirrors_kb_id", "todo_mirrors", ["kb_id"])
    op.create_index("ix_todo_mirrors_hub_note_id", "todo_mirrors", ["hub_note_id"])
    op.create_index("ix_todo_mirrors_source_note_id", "todo_mirrors", ["source_note_id"])
    op.create_index("ix_todo_mirrors_kb_status", "todo_mirrors", ["kb_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_todo_mirrors_kb_status", table_name="todo_mirrors")
    op.drop_index("ix_todo_mirrors_source_note_id", table_name="todo_mirrors")
    op.drop_index("ix_todo_mirrors_hub_note_id", table_name="todo_mirrors")
    op.drop_index("ix_todo_mirrors_kb_id", table_name="todo_mirrors")
    op.drop_table("todo_mirrors")

    op.drop_table("system_settings")

    op.drop_index("ix_note_revisions_note_created", table_name="note_revisions")
    op.drop_index("ix_note_revisions_note_id", table_name="note_revisions")
    op.drop_index("ix_note_revisions_kb_id", table_name="note_revisions")
    op.drop_table("note_revisions")

    op.drop_column("knowledge_bases", "todo_sync_last_at")
    op.drop_column("knowledge_bases", "todo_sync_interval_hours")
    op.drop_column("knowledge_bases", "wiki_compile_last_status")
    op.drop_column("knowledge_bases", "wiki_compile_last_at")
    op.drop_column("knowledge_bases", "wiki_compile_interval_hours")
    op.drop_column("knowledge_bases", "sort_order")
