"""桌面版便携 Python 的站点钩子：尽力阻止本机执行代码访问外部网络。

打包脚本会把本文件复制到便携 Python 的 ``Lib/site-packages/sitecustomize.py``。
Python 启动时会自动导入它（即使使用 ``-I``），因此 Notebook 内核与一次性代码
块都会在 ``socket`` 层被限制为 loopback。

边界说明：这不是安全沙箱。通过 ``ctypes`` 直接调用 Winsock、启动原生程序或
使用其他语言运行时仍可绕过；真正的外联防护由桌面宿主的 WebView2 请求拦截与
后端 :mod:`app.services.offline_guard` 负责。这里只降低误连外部地址的风险。
"""

from __future__ import annotations

import ipaddress
import sys

_ERROR = "桌面版本机执行已禁用外部网络连接，仅允许访问 127.0.0.1 / ::1。"
_ALLOWED_NAMES = {"localhost", "localhost.localdomain"}


def _is_loopback(host: object) -> bool:
    if host is None or host == "":
        # getaddrinfo(None, ...) 用于本地监听，不会发起外联。
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    name = str(host).strip().strip("[]").rstrip(".").lower()
    if not name:
        return True
    if name in _ALLOWED_NAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _check_address(address: object) -> bool:
    if isinstance(address, tuple):
        # AF_INET / AF_INET6 为 (host, port, ...)；AF_UNIX 的抽象命名空间也
        # 可能是 tuple，按本地地址放行。
        if len(address) >= 2 and isinstance(address[1], int):
            return _is_loopback(address[0])
    # AF_UNIX 路径、Windows 命名管道等一律视为本机资源。
    return True


def _audit(event: str, args: tuple) -> None:
    if event == "socket.connect":
        address = args[1] if len(args) > 1 else None
        if not _check_address(address):
            raise PermissionError(_ERROR)
    elif event in ("socket.getaddrinfo", "socket.gethostbyname"):
        host = args[0] if args else None
        if not _is_loopback(host):
            raise PermissionError(_ERROR)


def _install() -> None:
    # 避免重复安装（多次导入或子解释器）。
    if getattr(sys, "_kiwi_desktop_network_guard", False):
        return
    sys._kiwi_desktop_network_guard = True  # type: ignore[attr-defined]
    sys.addaudithook(_audit)


_install()
del _install
