"""用户手写笔记及四种组织维度（文件夹/标签/双向链接）。"""

import uuid
from typing import Literal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPkMixin

NoteStatus = Literal["active", "archived", "trash"]
NoteViewMode = Literal["edit", "outline", "split", "read"]
# 工作区节点类型：文档 / 数据表 / 外链 / 导入 / 画布
NoteKind = Literal["doc", "database", "link", "import", "canvas"]


class NoteFolder(UUIDPkMixin, Base):
    """笔记文件夹树。"""

    __tablename__ = "note_folders"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("note_folders.id", ondelete="CASCADE"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    # 置顶：在同一层级内优先展示
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class NoteTag(UUIDPkMixin, Base):
    """笔记标签，支持嵌套。"""

    __tablename__ = "note_tags"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("note_tags.id", ondelete="CASCADE"), nullable=True
    )
    __table_args__ = (UniqueConstraint("kb_id", "name", name="uq_note_tag_kb_name"),)


class NoteTagLink(Base):
    """笔记↔标签 多对多。"""

    __tablename__ = "note_tag_links"

    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("note_tags.id", ondelete="CASCADE"), primary_key=True
    )


class Note(UUIDPkMixin, Base):
    """笔记 / 工作区节点（文档、数据表、链接、导入）。"""

    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_kb_folder", "kb_id", "folder_id"),
        Index("ix_notes_kb_kind", "kb_id", "kind"),
        Index("ix_notes_kb_folder_sort", "kb_id", "folder_id", "sort_order"),
        Index("ix_notes_kb_parent_sort", "kb_id", "parent_note_id", "sort_order"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="doc", nullable=False)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("note_folders.id", ondelete="SET NULL"), nullable=True
    )
    # 笔记树：子笔记挂在父笔记下。父笔记永久删除时子笔记提升到所属分组。
    parent_note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    view_mode: Mapped[str] = mapped_column(String(12), default="edit", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 链接元数据 / 导入状态等结构化附加信息
    props_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    kb = relationship("KnowledgeBase", back_populates="notes")
    tags: Mapped[list[NoteTag]] = relationship(secondary="note_tag_links", lazy="selectin")
    folder = relationship("NoteFolder", lazy="joined")

    @property
    def tag_names(self) -> list[str]:
        """序列化用：标签名列表（按名称稳定排序）。

        写接口在 commit 后通过 `_tag_names_override` 注入最新名称，避免
        在异步会话中对已过期关系触发隐式 lazy load。
        """
        override = self.__dict__.get("_tag_names_override")
        if override is not None:
            return sorted(override)
        return sorted(tag.name for tag in self.tags)

    @property
    def wiki_page_id(self) -> uuid.UUID | None:
        """关联的 Wiki 页面（存于 props_json，兼容历史数据）。"""
        raw = (self.props_json or {}).get("wiki_page_id")
        try:
            return uuid.UUID(str(raw)) if raw else None
        except (ValueError, TypeError):
            return None

    def __repr__(self) -> str:
        return f"<Note {self.title}>"


class NoteTemplate(UUIDPkMixin, Base):
    """知识库级笔记模板：预填标题、正文结构、标签与属性。"""

    __tablename__ = "note_templates"
    __table_args__ = (Index("ix_note_templates_kb_sort", "kb_id", "sort_order"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(32), default="note", nullable=False)
    # 新建笔记时的默认标题（支持 {{date}} 占位）
    title_pattern: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tags_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    props_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class NoteLink(Base):
    """笔记间双向链接，附带引用上下文。"""

    __tablename__ = "note_links"
    __table_args__ = (UniqueConstraint("from_note_id", "to_note_id", name="uq_note_link_pair"),)

    from_note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    to_note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    context_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
