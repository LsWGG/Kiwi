"""问答会话：持久化历史消息、检索范围与页面级模型选择。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class ChatSession(UUIDPkMixin, Base):
    """一次问答会话。

    消息以 JSONB 数组保存（role / content / citations / created_at），
    单用户本地应用无需拆表；会话可跨知识库，因此不绑定 kb_id。
    """

    __tablename__ = "chat_sessions"

    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    # {"kb_ids": [...], "scope": "kb|multi|global"}
    scope_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    intent: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    llm_config_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("llm_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    messages_json: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ChatSession {self.id} {self.title!r}>"
