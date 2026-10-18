"""Wiki 页面（LLM 编译产物）与页面间链接。"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPkMixin

WikiPageType = Literal["entity", "concept", "summary", "synthesis"]


class WikiPage(UUIDPkMixin, Base):
    """LLM 维护的 Wiki 页面。human_edited=true 保护人工覆写不被编译覆盖。"""

    __tablename__ = "wiki_pages"
    __table_args__ = (Index("ix_wiki_kb_slug", "kb_id", "slug", unique=True),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    page_type: Mapped[str] = mapped_column(String(20), default="entity", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    body_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    frontmatter_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # 编译来源素材 id 列表
    compiled_from_source_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    version: Mapped[int] = mapped_column(default=1, nullable=False)
    human_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    kb = relationship("KnowledgeBase", back_populates="wiki_pages")

    def __repr__(self) -> str:
        return f"<WikiPage {self.slug}>"


class WikiLintReport(UUIDPkMixin, Base):
    """一次 Wiki 健康检查的快照：总览摘要与报告内容都持久化。"""

    __tablename__ = "wiki_lint_reports"
    __table_args__ = (
        Index("ix_wiki_lint_reports_kb_generated", "kb_id", "generated_at"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    semantic_status: Mapped[str] = mapped_column(
        String(20), default="skipped", nullable=False
    )
    semantic_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    issues_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    kb = relationship("KnowledgeBase")


class WikiLink(Base):
    """Wiki 页面间引用边（知识图谱）。"""

    __tablename__ = "wiki_links"
    __table_args__ = (Index("ix_wiki_links_from_to", "from_page_id", "to_page_id"),)

    from_page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="CASCADE"), primary_key=True
    )
    to_page_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("wiki_pages.id", ondelete="CASCADE"), primary_key=True
    )
    link_type: Mapped[str] = mapped_column(
        String(20), default="reference", nullable=False
    )  # reference/related/conflict
