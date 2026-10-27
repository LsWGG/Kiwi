"""素材原文件路径解析。

历史数据（或开发实例与容器共享同一个数据库时）里的 ``Source.raw_path`` 可能
是 ``data/uploads/<kb>/<file>`` 这样的相对路径。它依赖进程 CWD，换一个环境就
解析到不存在的目录，表现为 ``no such file: 'data/uploads/...'``。

这里统一把相对路径映射到当前 ``settings.upload_dir``，并且不再依赖 CWD。
"""

from __future__ import annotations

from pathlib import Path

from app.config import settings


def resolve_raw_path(raw_path: str | Path) -> Path:
    """把 ``Source.raw_path`` 解析成当前环境可用的路径。"""
    path = Path(raw_path)
    if path.is_absolute():
        return path

    upload_root = Path(settings.upload_dir)
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        # data/uploads/<kb>/<file> -> <upload_dir>/<kb>/<file>
        if part == upload_root.name:
            return upload_root.joinpath(*parts[index + 1 :])
    return upload_root / path
