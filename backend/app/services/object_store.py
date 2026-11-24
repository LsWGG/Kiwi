"""文件对象存储：本地目录（默认）与 S3 / MinIO 可切换。

存储键是相对 ``upload_dir`` 的完整路径，例如：

- ``media/<kb_id>/<uuid>.png``（笔记正文 / 附件，URL 为 ``/media/<...>``）
- ``<kb_id>/<source-file>``（素材原文件）
- ``media/theme-backgrounds/<name>``、``media/branding/<name>``

数据库里的 ``NoteAttachment.storage_path`` 仍是相对 ``media/`` 的键，写入时
拼上 ``media/`` 前缀即可。这样本地、S3 与历史数据可以共用同一套路径。
"""

from __future__ import annotations

import asyncio
import mimetypes
import tempfile
import uuid
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import AsyncIterator

from app.config import settings

UPLOAD_ROOT = "uploads"
CHUNK_SIZE = 1024 * 1024
# S3 上传前先落到临时文件：避免把大视频整个读进内存。
SPOOL_MAX_BYTES = 8 * 1024 * 1024


class ObjectStoreError(RuntimeError):
    """可直接展示给用户的存储错误。"""


@dataclass(frozen=True)
class ObjectStat:
    key: str
    size: int
    content_type: str = "application/octet-stream"
    etag: str = ""
    last_modified: float | None = None


def normalize_key(key: str) -> str:
    """规范化对象键并拒绝目录穿越。"""
    key = str(key or "").replace("\\", "/").lstrip("/")
    parts = [part for part in key.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ObjectStoreError("非法存储路径")
    return "/".join(parts)


def guess_content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class ObjectStore(ABC):
    """对象存储接口；键相对 ``upload_dir``。"""

    @abstractmethod
    async def save_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str = "",
    ) -> ObjectStat:
        ...

    async def save_bytes(
        self, key: str, data: bytes, *, content_type: str = ""
    ) -> ObjectStat:
        async def one() -> AsyncIterator[bytes]:
            yield data

        return await self.save_stream(key, one(), content_type=content_type)

    def save_bytes_sync(
        self, key: str, data: bytes, *, content_type: str = ""
    ) -> ObjectStat:
        """给同步解析器 / 导入器使用；需在非事件循环线程调用。"""
        raise ObjectStoreError("当前存储后端不支持同步写入")

    async def read_bytes(self, key: str) -> bytes:
        chunks: list[bytes] = []
        async for chunk in self.open(key):
            chunks.append(chunk)
        return b"".join(chunks)

    @abstractmethod
    async def stat(self, key: str) -> ObjectStat | None:
        ...

    @abstractmethod
    async def open(
        self, key: str, *, start: int = 0, end: int | None = None
    ) -> AsyncIterator[bytes]:
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    async def list(self, prefix: str = "") -> list[ObjectStat]:
        ...

    def local_path(self, key: str) -> Path | None:
        """本地后端返回磁盘路径；S3 返回 None。"""
        return None

    def media_url(self, key: str) -> str:
        normalized = normalize_key(key)
        if not normalized.startswith("media/"):
            raise ObjectStoreError("不是媒体对象")
        return f"/media/{normalized[len('media/') :]}"

    @contextmanager
    def materialize_sync(self, key: str):
        """同步代码（PDF / DOCX / OCR / 附件解析）使用的本地文件视图。"""
        path = self.local_path(key)
        if path is not None and path.is_file():
            yield path
            return
        raise ObjectStoreError("文件不存在")

    @asynccontextmanager
    async def materialize(self, key: str):
        """给必须使用本地 Path 的库使用：本地直接给路径，S3 下载到临时文件。"""
        path = self.local_path(key)
        if path is not None:
            yield path
            return
        stat = await self.stat(key)
        if stat is None:
            raise ObjectStoreError("文件不存在")
        suffix = Path(normalize_key(key)).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            import aiofiles

            async with aiofiles.open(temp_path, "wb") as out:
                async for chunk in self.open(key):
                    await out.write(chunk)
            yield temp_path
        finally:
            temp_path.unlink(missing_ok=True)


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / normalize_key(key)).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ObjectStoreError("非法存储路径")
        return path

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

    async def save_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str = "",
    ) -> ObjectStat:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
        size = 0
        try:
            with partial.open("wb") as out:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    out.write(chunk)
            if size == 0:
                raise ObjectStoreError("空文件")
            partial.replace(path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        info = path.stat()
        return ObjectStat(
            key=normalize_key(key),
            size=size,
            content_type=content_type or guess_content_type(key),
            etag=f'"{info.st_mtime_ns:x}-{size:x}"',
            last_modified=info.st_mtime,
        )

    async def stat(self, key: str) -> ObjectStat | None:
        path = self._path(key)
        try:
            info = path.stat()
        except OSError:
            return None
        if not path.is_file():
            return None
        return ObjectStat(
            key=normalize_key(key),
            size=info.st_size,
            content_type=guess_content_type(key),
            etag=f'"{info.st_mtime_ns:x}-{info.st_size:x}"',
            last_modified=info.st_mtime,
        )

    async def open(
        self, key: str, *, start: int = 0, end: int | None = None
    ) -> AsyncIterator[bytes]:
        import aiofiles

        path = self._path(key)
        remaining = None if end is None else max(0, end - start + 1)
        async with aiofiles.open(path, "rb") as handle:
            if start:
                await handle.seek(start)
            while remaining is None or remaining > 0:
                chunk = await handle.read(
                    CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
                )
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk

    def save_bytes_sync(
        self, key: str, data: bytes, *, content_type: str = ""
    ) -> ObjectStat:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        info = path.stat()
        return ObjectStat(
            key=normalize_key(key),
            size=len(data),
            content_type=content_type or guess_content_type(key),
            etag=f'"{info.st_mtime_ns:x}-{len(data):x}"',
            last_modified=info.st_mtime,
        )

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def list(self, prefix: str = "") -> list[ObjectStat]:
        base = self._path(prefix) if prefix else self.root
        if not base.is_dir():
            return []
        items: list[ObjectStat] = []
        for path in base.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                key = path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            info = path.stat()
            items.append(
                ObjectStat(
                    key=key,
                    size=info.st_size,
                    content_type=guess_content_type(key),
                    etag=f'"{info.st_mtime_ns:x}-{info.st_size:x}"',
                    last_modified=info.st_mtime,
                )
            )
        return items


class S3ObjectStore(ObjectStore):
    """S3 兼容后端（MinIO / 云对象存储）。"""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        prefix: str = UPLOAD_ROOT,
        connect_timeout: float = 10.0,
        read_timeout: float = 60.0,
        local_fallback: LocalObjectStore | None = None,
    ):
        if not endpoint or not bucket or not access_key or not secret_key:
            raise ObjectStoreError(
                "S3 存储未配置完整：需要 endpoint / bucket / access key / secret key"
            )
        self.endpoint = endpoint
        self.bucket = bucket
        self.region = region
        self.prefix = prefix.strip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.local_fallback = local_fallback
        self._client = None

    def _client_or_create(self):
        if self._client is None:
            import boto3
            from botocore.client import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    connect_timeout=self.connect_timeout,
                    read_timeout=self.read_timeout,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return self._client

    def _full_key(self, key: str) -> str:
        normalized = normalize_key(key)
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    async def save_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str = "",
    ) -> ObjectStat:
        spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES)
        size = 0
        try:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                spool.write(chunk)
            if size == 0:
                raise ObjectStoreError("空文件")
            spool.seek(0)
            client = self._client_or_create()
            await asyncio.to_thread(
                client.upload_fileobj,
                spool,
                self.bucket,
                self._full_key(key),
                ExtraArgs={
                    "ContentType": content_type or guess_content_type(key)
                },
            )
        finally:
            spool.close()
        return ObjectStat(
            key=normalize_key(key),
            size=size,
            content_type=content_type or guess_content_type(key),
        )

    async def stat(self, key: str) -> ObjectStat | None:
        from botocore.exceptions import ClientError

        client = self._client_or_create()
        try:
            head = await asyncio.to_thread(
                client.head_object,
                Bucket=self.bucket,
                Key=self._full_key(key),
            )
        except ClientError as e:
            code = str(e.response.get("Error", {}).get("Code") or "")
            if code in ("404", "NoSuchKey", "NotFound"):
                if self.local_fallback is not None:
                    return await self.local_fallback.stat(key)
                return None
            raise ObjectStoreError(f"读取存储信息失败：{e}") from e
        modified = head.get("LastModified")
        return ObjectStat(
            key=normalize_key(key),
            size=int(head.get("ContentLength") or 0),
            content_type=str(
                head.get("ContentType") or guess_content_type(key)
            ),
            etag=str(head.get("ETag") or "").strip('"'),
            last_modified=(
                modified.astimezone(timezone.utc).timestamp()
                if modified is not None
                else None
            ),
        )

    @contextmanager
    def materialize_sync(self, key: str):
        from botocore.exceptions import ClientError

        client = self._client_or_create()
        handle = tempfile.NamedTemporaryFile(
            delete=False, suffix=Path(normalize_key(key)).suffix
        )
        temp_path = Path(handle.name)
        try:
            try:
                client.download_fileobj(
                    self.bucket, self._full_key(key), handle
                )
            except ClientError as e:
                code = str(e.response.get("Error", {}).get("Code") or "")
                if (
                    code in ("404", "NoSuchKey", "NotFound")
                    and self.local_fallback is not None
                ):
                    with self.local_fallback.materialize_sync(key) as local:
                        yield local
                    return
                raise ObjectStoreError(f"读取媒体失败：{e}") from e
            handle.flush()
            handle.close()
            yield temp_path
        finally:
            handle.close()
            temp_path.unlink(missing_ok=True)

    async def open(
        self, key: str, *, start: int = 0, end: int | None = None
    ) -> AsyncIterator[bytes]:
        from botocore.exceptions import ClientError

        client = self._client_or_create()
        kwargs = {"Bucket": self.bucket, "Key": self._full_key(key)}
        if start or end is not None:
            kwargs["Range"] = f"bytes={start}-{'' if end is None else end}"
        try:
            response = await asyncio.to_thread(client.get_object, **kwargs)
        except ClientError as e:
            code = str(e.response.get("Error", {}).get("Code") or "")
            if code in ("404", "NoSuchKey", "NotFound") and self.local_fallback is not None:
                async for chunk in self.local_fallback.open(
                    key, start=start, end=end
                ):
                    yield chunk
                return
            raise ObjectStoreError(f"读取媒体失败：{e}") from e
        body = response["Body"]
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    def save_bytes_sync(
        self, key: str, data: bytes, *, content_type: str = ""
    ) -> ObjectStat:
        client = self._client_or_create()
        client.put_object(
            Bucket=self.bucket,
            Key=self._full_key(key),
            Body=data,
            ContentType=content_type or guess_content_type(key),
        )
        return ObjectStat(
            key=normalize_key(key),
            size=len(data),
            content_type=content_type or guess_content_type(key),
        )

    async def delete(self, key: str) -> None:
        client = self._client_or_create()
        await asyncio.to_thread(
            client.delete_object,
            Bucket=self.bucket,
            Key=self._full_key(key),
        )
        if self.local_fallback is not None:
            await self.local_fallback.delete(key)

    async def list(self, prefix: str = "") -> list[ObjectStat]:
        client = self._client_or_create()
        search = self._full_key(prefix) if prefix else self.prefix
        paginator = client.get_paginator("list_objects_v2")
        items: list[ObjectStat] = []

        def collect() -> list[dict]:
            pages = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=search):
                pages.append(page)
            return pages

        pages = await asyncio.to_thread(collect)
        for page in pages:
            for item in page.get("Contents", []):
                full = str(item.get("Key") or "")
                if not full or full.endswith("/"):
                    continue
                key = (
                    full[len(self.prefix) + 1 :]
                    if self.prefix and full.startswith(self.prefix + "/")
                    else full
                )
                modified = item.get("LastModified")
                items.append(
                    ObjectStat(
                        key=key,
                        size=int(item.get("Size") or 0),
                        content_type=guess_content_type(key),
                        etag=str(item.get("ETag") or "").strip('"'),
                        last_modified=(
                            modified.astimezone(timezone.utc).timestamp()
                            if modified is not None
                            else None
                        ),
                    )
                )
        if self.local_fallback is not None:
            seen = {item.key for item in items}
            for item in await self.local_fallback.list(prefix):
                if item.key not in seen:
                    items.append(item)
        return items


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    """返回进程级对象存储；首次调用时按配置创建。"""
    global _store
    if _store is not None:
        return _store
    if settings.media_backend == "s3":
        _store = S3ObjectStore(
            endpoint=settings.s3_endpoint,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key.get_secret_value(),
            secret_key=settings.s3_secret_key.get_secret_value(),
            region=settings.s3_region,
            prefix=settings.s3_prefix,
            connect_timeout=settings.s3_connect_timeout,
            read_timeout=settings.s3_read_timeout,
            local_fallback=(
                LocalObjectStore(settings.upload_dir)
                if settings.media_local_fallback
                else None
            ),
        )
    else:
        _store = LocalObjectStore(settings.upload_dir)
    return _store


def reset_object_store() -> None:
    """测试或运行时切换配置后重建存储实例。"""
    global _store
    _store = None


__all__ = [
    "LocalObjectStore",
    "ObjectStat",
    "ObjectStore",
    "ObjectStoreError",
    "S3ObjectStore",
    "get_object_store",
    "guess_content_type",
    "normalize_key",
    "reset_object_store",
]
