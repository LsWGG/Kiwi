"""主题插件资源：背景图、预览图、字体、背景视频等二进制文件。

主题包以 zip 导入，`assets/` 下的文件按原相对路径存入本表；服务端按
`/api/plugins/{plugin_id}/asset/{path}` 原样下发。资源随数据库同步，避免
本地与生产共用数据库但媒体目录不共享时出现 404。
"""

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PluginAsset(Base):
    __tablename__ = "plugin_assets"

    plugin_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plugins.id", ondelete="CASCADE"), primary_key=True
    )
    # zip 内相对路径，例如 assets/paper.webp；不含前导 assets/ 时也允许。
    path: Mapped[str] = mapped_column(String(300), primary_key=True)
    content_type: Mapped[str] = mapped_column(
        String(100), default="application/octet-stream", nullable=False
    )
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
