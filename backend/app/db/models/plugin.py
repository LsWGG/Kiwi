"""插件 / 区块注册表。

插件有两种形态：
- template：声明式 manifest，只插入 Markdown 模板，不执行第三方代码；
- component：zip 内附带单文件 ESM，前端在编辑器 / 阅读态中加载并渲染交互区块。

脚本与样式原文随插件记录持久化，启用状态和 manifest 也在同一张表；
导入 / 删除均为显式操作。
"""

from typing import Any

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin


class Plugin(UUIDPkMixin, Base):
    __tablename__ = "plugins"
    __table_args__ = (Index("ix_plugins_enabled_key", "enabled", "key"),)

    # 全局唯一 slug，作为区块命名空间（`<key>:<block type>`）
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    author: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    icon: Mapped[str] = mapped_column(String(40), default="puzzle", nullable=False)
    homepage: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # template（声明式模板） / component（zip 内附可执行 ESM）
    kind: Mapped[str] = mapped_column(String(20), default="template", nullable=False)
    # 组件插件入口相对路径（默认 index.js）；模板插件为空
    entry: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # 组件插件脚本 / 样式原文，由 /api/plugins/{id}/bundle.js、style.css 下发
    script: Mapped[str] = mapped_column(Text, default="", nullable=False)
    style: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # manual（界面创建） / import（导入 manifest / zip）
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    # 完整规范化 manifest：blocks / settings 等
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return list((self.manifest or {}).get("blocks") or [])
