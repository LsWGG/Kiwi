"""笔记只读分享链接。

分享链接持有不可猜测的随机 token，可设置有效期与访问密码；笔记正文
仍以 ``notes.body_md`` 为唯一来源，分享表只保存访问控制元数据。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class NoteShare(UUIDPkMixin, Base):
    """一条只读分享记录；撤销后保留审计痕迹但不再可访问。"""

    __tablename__ = "note_shares"
    __table_args__ = (
        Index("ix_note_shares_note", "note_id", "created_at"),
        Index("ix_note_shares_token", "token", unique=True),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    # URL 中的随机凭证，使用 secrets.token_urlsafe 生成
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    # 可选访问密码：PBKDF2 哈希 + 盐，永不回传明文
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash and self.password_salt)
