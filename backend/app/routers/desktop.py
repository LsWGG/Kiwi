"""桌面模式 API：运行状态、离线开关与本机执行策略。

仅在 ``KIWI_DESKTOP_MODE=true`` 时注册；即使被误挂载，请求也会得到 404，
不向 Docker 部署暴露桌面专用接口。Docker 行为不受影响。
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.build_info import APP_VERSION
from app.config import settings
from app.db.models import LLMConfig
from app.db.session import async_session_factory
from app.schemas.desktop import (
    DesktopCapabilitiesOut,
    DesktopEmbeddingOut,
    DesktopLlmOut,
    DesktopLocalCodeOut,
    DesktopSettingsOut,
    DesktopSettingsUpdate,
    DesktopStatusOut,
)
from app.services import desktop_settings, embedder, offline_guard
from app.services.notebook_kernel import kernel_manager

logger = logging.getLogger("kiwi.desktop")


def require_desktop_mode() -> None:
    if not settings.desktop_mode:
        # 伪装成不存在，避免暴露桌面专用接口。
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/api/desktop",
    tags=["desktop"],
    dependencies=[Depends(require_desktop_mode)],
)

# 内部接口不属于 /api：AccessControlMiddleware 只保护 /api、/media、/metrics，
# 因此这里自行校验 loopback 与控制令牌。控制令牌由 .NET 宿主生成并通过环境
# 变量传给 runtime，不写状态文件。
internal_router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_desktop_mode)],
    include_in_schema=False,
)


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


@internal_router.post("/shutdown")
def request_shutdown(request: Request) -> dict[str, str]:
    """桌面运行时优雅退出入口；仅本机 + 控制令牌可触发。"""
    client_host = request.client.host if request.client else ""
    if not _is_loopback_host(client_host):
        raise HTTPException(403, "仅允许本机调用")
    expected = settings.desktop_control_token
    supplied = request.headers.get("x-kiwi-control-token", "")
    if not expected or not hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(403, "控制令牌无效")
    callback = getattr(request.app.state, "desktop_shutdown_callback", None)
    if callback is None:
        raise HTTPException(503, "桌面运行时尚未就绪")
    callback()
    return {"status": "shutting-down"}


def portable_python_path() -> Path | None:
    """桌面版便携 Python 路径；未配置或文件不存在时返回 None。"""
    raw = settings.desktop_python.strip()
    if not raw:
        return None
    path = Path(raw)
    try:
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def _embedding_state() -> DesktopEmbeddingOut:
    provider = embedder.runtime_config().provider.strip().lower()
    enabled = provider not in {"", "none", "disabled", "off"}
    if not enabled:
        normalized = "none"
    elif provider in {"openai", "remote", "api"}:
        normalized = "openai"
    else:
        normalized = "local"
    return DesktopEmbeddingOut(
        enabled=enabled,
        provider=normalized,
        state="configured" if enabled else "disabled",
    )


def _local_code_state(cfg: desktop_settings.DesktopSettings) -> DesktopLocalCodeOut:
    return DesktopLocalCodeOut(
        enabled=cfg.local_code_execution,
        available=portable_python_path() is not None,
        implementation="windows-job" if os.name == "nt" else "bubblewrap",
    )


async def _llm_configured() -> bool:
    try:
        async with async_session_factory() as db:
            total = (await db.execute(select(func.count(LLMConfig.id)))).scalar_one()
    except Exception as exc:  # noqa: BLE001 - 状态接口不应因数据库短暂不可用而失败
        logger.warning("读取大模型配置失败：%s", exc)
        return False
    return bool(total)


@router.get("/status", response_model=DesktopStatusOut)
async def desktop_status() -> DesktopStatusOut:
    cfg = desktop_settings.load()
    local_code = _local_code_state(cfg)
    log_dir = settings.log_file.parent if settings.log_file else settings.data_dir / "logs"
    return DesktopStatusOut(
        desktop=True,
        version=APP_VERSION,
        data_dir=str(settings.data_dir),
        log_dir=str(log_dir),
        embedding=_embedding_state(),
        llm=DesktopLlmOut(
            configured=await _llm_configured(),
            remote_allowed=cfg.allow_online_models,
        ),
        local_code=local_code,
        capabilities=DesktopCapabilitiesOut(
            online_models=cfg.allow_online_models,
            link_fetch=False,
            remote_import=False,
            online_ocr=False,
            feishu=False,
            web_push=False,
            study_web_search=False,
            youtube_embed=False,
            external_images=False,
            local_code_execution=bool(
                cfg.local_code_execution and local_code.available
            ),
        ),
    )


@router.get("/settings", response_model=DesktopSettingsOut)
def get_desktop_settings() -> DesktopSettingsOut:
    return DesktopSettingsOut(**asdict(desktop_settings.load()))


@router.put("/settings", response_model=DesktopSettingsOut)
def update_desktop_settings(data: DesktopSettingsUpdate) -> DesktopSettingsOut:
    current = desktop_settings.load()
    enable_online = data.allow_online_models is True and not current.allow_online_models
    enable_local = data.local_code_execution is True and not current.local_code_execution
    if (enable_online or enable_local) and not data.acknowledge_risk:
        raise HTTPException(
            status_code=400,
            detail="开启外部模型接口或本机代码执行前，请先确认相应风险",
        )
    if enable_local and portable_python_path() is None:
        raise HTTPException(
            status_code=409,
            detail="未找到桌面版便携 Python，请重新安装应用后再开启本机代码执行",
        )

    now = datetime.now(timezone.utc).isoformat()
    if enable_online:
        current.acknowledged_online_models_at = now
    if enable_local:
        current.acknowledged_local_code_at = now
    if data.allow_online_models is not None:
        current.allow_online_models = data.allow_online_models
    if data.local_code_execution is not None:
        current.local_code_execution = data.local_code_execution
    if data.local_code_timeout_seconds is not None:
        current.local_code_timeout_seconds = data.local_code_timeout_seconds

    saved = desktop_settings.save(current)
    # 离线策略立即生效；关闭外部模型时同时作废已登记端点，避免 TTL 内残留。
    offline_guard.refresh_policy()
    if not saved.allow_online_models:
        offline_guard.revoke_endpoints()
    if data.local_code_execution is False:
        # 关闭本机执行后立即回收内核，避免旧进程继续运行。
        try:
            kernel_manager.shutdown_all()
        except Exception as exc:  # noqa: BLE001 - 清理失败不应回滚设置
            logger.warning("关闭本机执行时清理内核失败：%s", exc)
    return DesktopSettingsOut(**asdict(saved))
