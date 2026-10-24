"""Web Push 订阅：每台浏览器一条记录，供到期复习 / 周报提醒推送。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class PushSubscription(UUIDPkMixin, Base):
    """浏览器推送订阅。

    endpoint 由浏览器推送服务分配，唯一；p256dh / auth 是客户端公钥与
    认证密钥，发送时原样交给 Web Push 协议做载荷加密。
    """

    __tablename__ = "push_subscriptions"

    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(200), nullable=False)
    auth: Mapped[str] = mapped_column(String(100), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self) -> str:
        return f"<PushSubscription {self.id} {self.endpoint[:40]}>"
