"""桌面离线网络防护：socket 审计钩子 + 模型端点白名单。

桌面 runtime 在导入 ``app.main`` 之前调用 :func:`install`。钩子拦截
``socket.connect`` / ``socket.getaddrinfo`` / ``socket.gethostbyname``：

- loopback（127.0.0.1、::1、localhost）始终放行，供 PostgreSQL、Qdrant
  与 uvicorn 使用。
- 非 loopback 主机只有在「桌面设置允许外部模型」且通过
  :func:`register_endpoint` 显式登记后才放行；登记带 TTL，模型调用前刷新。
- 其余外联一律抛出 :class:`OfflineNetworkBlocked`。

该钩子无法覆盖 C 扩展或子进程；桌面版同时使用路由守卫与 WebView2 网络层
防护。Docker / 源码部署不调用 :func:`install`，行为完全不变。
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from app.config import settings
from app.services import desktop_settings

logger = logging.getLogger("kiwi.desktop.offline")

DEFAULT_ENDPOINT_TTL = 600.0
# 桌面设置是本地 JSON，钩子又位于每次连接的热路径上；缓存两秒兼顾
# 即时生效与避免每次 socket 调用都读盘。
POLICY_TTL = 2.0
MAX_LOGGED_BLOCKS = 50

# socket 审计事件：TCP/UDP connect、DNS 解析。Unix socket 的 address 是
# 字符串，属于本机 IPC，不在这里拦截。
_SOCKET_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}

_state = threading.local()
_installed = False
_install_lock = threading.Lock()
_endpoints: dict[str, float] = {}
_endpoints_lock = threading.Lock()
_policy_cache: tuple[float, bool] | None = None
_logged_blocks: set[str] = set()


class OfflineNetworkBlocked(PermissionError):
    """桌面离线模式拦截了未登记的外部网络访问。"""


class OnlineModelsDisabled(PermissionError):
    """桌面设置未允许外部模型接口。"""


def _normalize_host(host) -> str:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return ""
    return host.strip().lower().rstrip(".").strip("[]")


def is_loopback_host(host: str) -> bool:
    """localhost / 127.0.0.0/8 / ::1 / IPv4-mapped loopback。"""
    value = _normalize_host(host)
    if not value:
        return False
    if value == "localhost" or value.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def endpoint_host(url: str) -> str:
    """从 base URL 提取主机名；兼容省略 scheme 的 ``host:port``。"""
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    try:
        return _normalize_host(urlsplit(value).hostname or "")
    except ValueError:
        return ""


def online_models_allowed() -> bool:
    """当前是否允许连接外部模型；Docker / 未启用桌面模式时始终为真。"""
    global _policy_cache
    if not settings.desktop_mode:
        return True
    now = time.monotonic()
    cached = _policy_cache
    if cached is not None and now - cached[0] < POLICY_TTL:
        return cached[1]
    allowed = desktop_settings.load().allow_online_models
    _policy_cache = (now, allowed)
    return allowed


def refresh_policy() -> None:
    """桌面设置变更后立即生效（不必等待缓存过期）。"""
    global _policy_cache
    _policy_cache = None


def revoke_endpoints() -> None:
    """关闭外部模型开关时清空已登记的端点。"""
    with _endpoints_lock:
        _endpoints.clear()


@contextmanager
def _resolution_bypass():
    """只允许当前线程在登记端点时解析 DNS，避免钩子自我递归阻断。"""
    previous = getattr(_state, "bypass", False)
    _state.bypass = True
    try:
        yield
    finally:
        _state.bypass = previous


def register_endpoint(url: str, ttl: float = DEFAULT_ENDPOINT_TTL) -> None:
    """登记模型接口主机与解析出的 IP；未安装钩子时为空操作。

    未允许外部模型时直接抛出 :class:`OnlineModelsDisabled`，让调用方在
    发起请求前就得到明确错误，而不是等到 socket 层才失败。
    """
    if not _installed:
        return
    host = endpoint_host(url)
    if not host or is_loopback_host(host):
        return
    if not online_models_allowed():
        raise OnlineModelsDisabled(
            "桌面版未允许外部模型接口：请先在「设置 → 桌面」中开启"
            "「允许连接外部模型接口」并确认风险。"
        )

    expiry = time.monotonic() + max(0.0, float(ttl))
    keys = {host}
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # 域名：登记时解析一次，之后 connect 使用解析出的 IP 也能通过。
        with _resolution_bypass():
            try:
                infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise OfflineNetworkBlocked(
                    f"无法解析模型接口主机 {host}：{exc}"
                ) from exc
        keys.update(
            _normalize_host(info[4][0]) for info in infos if info[4]
        )

    now = time.monotonic()
    with _endpoints_lock:
        for key in [k for k, exp in _endpoints.items() if exp <= now]:
            _endpoints.pop(key, None)
        for key in keys:
            if key:
                _endpoints[key] = expiry


def _is_registered(host: str) -> bool:
    now = time.monotonic()
    with _endpoints_lock:
        expiry = _endpoints.get(host)
        if expiry is None:
            return False
        if expiry <= now:
            _endpoints.pop(host, None)
            return False
        return True


def _blocked(host: str) -> None:
    if host not in _logged_blocks and len(_logged_blocks) < MAX_LOGGED_BLOCKS:
        _logged_blocks.add(host)
        logger.warning("桌面离线模式已拦截外部网络访问：%s", host)
    raise OfflineNetworkBlocked(
        f"桌面版默认离线，已拦截外部网络访问：{host}。"
        "模型接口请先在桌面设置中允许外部模型；其他联网功能在桌面版不可用。"
    )


def _check_host(host, event: str) -> None:
    value = _normalize_host(host)
    if not value or is_loopback_host(value):
        return
    if _is_registered(value):
        if online_models_allowed():
            return
        raise OnlineModelsDisabled(
            f"桌面版已关闭外部模型接口，拒绝连接：{value}"
        )
    _blocked(value)


def _audit(event: str, args: tuple) -> None:
    if event not in _SOCKET_EVENTS:
        return
    if getattr(_state, "bypass", False):
        return

    if event == "socket.connect":
        address = args[1] if len(args) > 1 else None
        if isinstance(address, str) or address is None:
            return  # AF_UNIX / 已关闭的套接字
        if isinstance(address, tuple) and address:
            _check_host(address[0], event)
        return

    host = args[0] if args else None
    if host is None or host == "" or host == b"":
        return  # getaddrinfo(None, ...) 用于本机 bind
    _check_host(host, event)


def _scrub_proxy_env() -> None:
    """本机直连：避免系统代理把 loopback 请求转给外部代理进程。"""
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
    os.environ["no_proxy"] = "127.0.0.1,localhost,::1"


def install() -> bool:
    """安装审计钩子；仅 ``KIWI_OFFLINE_MODE=true`` 时生效，重复调用无副作用。"""
    global _installed
    with _install_lock:
        if _installed:
            return False
        if not settings.offline_mode:
            return False
        _scrub_proxy_env()
        sys.addaudithook(_audit)
        _installed = True
    logger.info("桌面离线审计钩子已启用：仅放行 loopback 与已登记模型端点")
    return True


def is_installed() -> bool:
    return _installed
