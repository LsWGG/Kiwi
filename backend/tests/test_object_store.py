"""对象存储：本地后端的契约与可选 S3/MinIO 集成测试。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.services.object_store import (
    LocalObjectStore,
    ObjectStoreError,
    S3ObjectStore,
)


async def test_local_store_roundtrip_and_range(tmp_path: Path):
    store = LocalObjectStore(tmp_path)
    stat = await store.save_bytes(
        "media/kb/demo.txt", b"hello-object-store", content_type="text/plain"
    )
    assert stat.size == len(b"hello-object-store")
    assert await store.read_bytes("media/kb/demo.txt") == b"hello-object-store"

    chunks = [chunk async for chunk in store.open("media/kb/demo.txt", start=6, end=11)]
    assert b"".join(chunks) == b"object"

    assert store.media_url("media/kb/demo.txt") == "/media/kb/demo.txt"
    assert [item.key for item in await store.list("media")] == [
        "media/kb/demo.txt"
    ]

    async with store.materialize("media/kb/demo.txt") as path:
        assert path.read_bytes() == b"hello-object-store"

    await store.delete("media/kb/demo.txt")
    assert await store.stat("media/kb/demo.txt") is None
    assert await store.list("media") == []


async def test_local_store_rejects_traversal(tmp_path: Path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ObjectStoreError):
        await store.save_bytes("../escape.txt", b"x")
    with pytest.raises(ObjectStoreError):
        store.media_url("kb/demo.txt")


async def test_s3_store_roundtrip_when_configured():
    endpoint = os.environ.get("KIWI_S3_TEST_ENDPOINT", "").strip()
    if not endpoint:
        pytest.skip("未设置 KIWI_S3_TEST_ENDPOINT，跳过 MinIO 集成测试")
    bucket = os.environ.get("KIWI_S3_TEST_BUCKET", "kiwi-media")
    key_prefix = os.environ.get("KIWI_S3_TEST_PREFIX", "uploads-pytest")
    store = S3ObjectStore(
        endpoint=endpoint,
        bucket=bucket,
        access_key=os.environ["KIWI_S3_TEST_ACCESS_KEY"],
        secret_key=os.environ["KIWI_S3_TEST_SECRET_KEY"],
        prefix=key_prefix,
        local_fallback=None,
    )
    key = f"media/__pytest__/{uuid.uuid4().hex}.txt"
    try:
        await store.save_bytes(key, b"hello-minio", content_type="text/plain")
        stat = await store.stat(key)
        assert stat is not None and stat.size == len(b"hello-minio")
        assert await store.read_bytes(key) == b"hello-minio"
        assert any(item.key == key for item in await store.list("media/__pytest__"))
    finally:
        await store.delete(key)
    assert await store.stat(key) is None
