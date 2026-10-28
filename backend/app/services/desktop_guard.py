"""桌面模式功能守卫：联网功能开关、模型 URL 策略与本机执行权限。

Docker / 源码部署（``desktop_mode=false``）下所有函数均为 no-op，现有行为
完全不变。桌面模式下：

- 链接抓取、远程导入、在线 OCR、飞书、Web Push、语雀在线导入、学习联网
  核查等非模型联网功能一律拒绝（HTTP 409）。
- 模型接口允许 loopback；非 loopback 地址必须先在桌面设置中显式允许外部
  模型（``allow_online_models``），否则返回 HTTP 400。
- 本机代码执行默认关闭，关闭时返回 HTTP 403。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

from app.config import settings
from app.services import desktop_settings
from app.services.offline_guard import is_loopback_host

# 供路由与状态接口共用的功能名。label 用于 409 文案。
FEATURE_LABELS = {
    "link_fetch": "网页链接抓取",
    "remote_import": "远程 URL 导入",
    "online_ocr": "在线 OCR",
    "feishu": "飞书妙记",
    "transcribe": "语音转写",
    "web_push": "Web Push 提醒",
    "study_web_search": "学习联网核查",
    "yuque_online": "语雀在线导入",
    "rerank": "外部重排模型",
}


def online_models_allowed() -> bool:
    return desktop_settings.online_models_allowed()


def require_online_feature(feature: str) -> None:
    """桌面模式下拒绝联网功能；Docker 下直接返回。"""
    if not settings.desktop_mode:
        return
    label = FEATURE_LABELS.get(feature, feature)
    raise HTTPException(
        status_code=409,
        detail=(
            f"桌面版已禁用{label}：桌面模式默认不发起外部网络请求。"
            "如需这些功能，请使用 Docker / Web 部署。"
        ),
    )


def validate_model_url(url: str) -> str:
    """校验模型接口地址并返回去空白后的值。

    仅在桌面模式生效：loopback 无需确认；外部地址要求
    ``allow_online_models=true``。Docker 下原样返回。
    """
    value = (url or "").strip()
    if not settings.desktop_mode or not value:
        return value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise HTTPException(400, "模型接口地址必须是 http:// 或 https:// 开头的 URL")
    if is_loopback_host(parts.hostname):
        return value
    if not online_models_allowed():
        raise HTTPException(
            status_code=400,
            detail=(
                "桌面版默认仅允许本机模型接口。该地址会把笔记正文、选中文本"
                "和问题发送到外部服务；如确需连接，请先在「设置 → 桌面」中"
                "开启「允许连接外部模型接口」并确认风险。"
            ),
        )
    return value


def require_local_execution() -> None:
    """桌面模式下本机代码执行必须显式开启（默认关闭）。"""
    if not settings.desktop_mode:
        return
    if not desktop_settings.load().local_code_execution:
        raise HTTPException(
            status_code=403,
            detail=(
                "桌面版本机代码执行默认关闭。请在「设置 → 桌面」中开启，"
                "并了解本机执行没有文件系统隔离。"
            ),
        )
    if os.name == "nt":
        raw = settings.desktop_python.strip()
        available = False
        if raw:
            try:
                available = Path(raw).is_file()
            except (OSError, ValueError):
                available = False
        if not available:
            raise HTTPException(
                status_code=503,
                detail="未找到桌面版便携 Python，请重新安装应用后再运行本机代码。",
            )
