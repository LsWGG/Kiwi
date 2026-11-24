"""素材原文件路径解析。

历史数据（或开发实例与容器共享同一个数据库时）里的 ``Source.raw_path`` 可能
是 ``data/uploads/<kb>/<file>`` 这样的相对路径。它依赖进程 CWD，换一个环境就
解析到不存在的目录，表现为 ``no such file: 'data/uploads/...'``。

这里统一把相对路径映射到当前 ``settings.upload_dir``，并且不再依赖 CWD。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from app.config import settings
from app.services.object_store import get_object_store


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


def storage_key(raw_path: str | Path) -> str | None:
    """把素材路径转换为相对 ``upload_dir`` 的对象键；外部绝对路径返回 None。"""
    path = Path(raw_path)
    root = Path(settings.upload_dir).resolve()
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            return None
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part == root.name:
            return "/".join(parts[index + 1 :])
    return path.as_posix()


async def save_source_bytes(
    kb_id, filename: str, data: bytes, *, content_type: str = ""
) -> str:
    """把素材写入对象存储（本地后端即写本地），返回相对 upload_dir 的键。"""
    key = f"{kb_id}/{filename}"
    await get_object_store().save_bytes(key, data, content_type=content_type)
    return key


async def delete_source(raw_path: str | Path) -> None:
    key = storage_key(raw_path)
    if key is not None:
        try:
            await get_object_store().delete(key)
        except Exception:  # noqa: BLE001 —— 清理失败不应阻断业务
            pass
        return
    try:
        Path(raw_path).unlink(missing_ok=True)
    except OSError:
        pass


async def read_source_bytes(raw_path: str | Path) -> bytes:
    key = storage_key(raw_path)
    if key is not None:
        return await get_object_store().read_bytes(key)
    return Path(raw_path).read_bytes()


@asynccontextmanager
async def materialize_raw_path(raw_path: str | Path):
    """给解析器 / 导出器等需要本地 Path 的代码准备素材。

    本地存在就直接复用；S3 模式下不存在时下载到临时文件，退出时删除。
    """
    key = storage_key(raw_path)
    local = resolve_raw_path(raw_path)
    if local.is_file():
        yield local
        return
    if key is None:
        raise FileNotFoundError(f"素材文件不存在：{raw_path}")
    async with get_object_store().materialize(key) as materialized:
        yield materialized
