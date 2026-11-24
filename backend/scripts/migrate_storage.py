"""把本地 upload_dir 中的文件迁移到 S3 / MinIO。

默认迁移 upload_dir 下的全部持久化文件：media/（笔记附件、图片、主题背景、
Branding）、素材原文件（<kb_id>/...）与笔记快照；chunks / transcribe / .tmp
等可重建缓存会跳过。也可用 ``--prefix`` 只迁移指定目录。

运行（在 backend 目录）：

    # 预演，不写对象存储
    KIWI_MEDIA_BACKEND=s3 python scripts/migrate_storage.py --dry-run

    # 迁移全部持久化文件，已存在且大小一致的对象会跳过
    KIWI_MEDIA_BACKEND=s3 python scripts/migrate_storage.py

    # 只迁移 media/
    KIWI_MEDIA_BACKEND=s3 python scripts/migrate_storage.py --prefix media

迁移期间可保持 ``KIWI_MEDIA_LOCAL_FALLBACK=true``，未迁移 / 迁移中的文件仍可读。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.object_store import (  # noqa: E402
    ObjectStoreError,
    S3ObjectStore,
    guess_content_type,
)

SKIP_DIRS = {"chunks", "transcribe", ".tmp"}
CHUNK = 1024 * 1024


def _iter_files(root: Path, prefixes: list[str]) -> list[tuple[Path, str]]:
    items: list[tuple[Path, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        key = rel.as_posix()
        if prefixes and "" not in prefixes and not any(
            key == p or key.startswith(p.rstrip("/") + "/") for p in prefixes
        ):
            continue
        items.append((path, key))
    return items


async def _migrate(args) -> int:
    if settings.media_backend != "s3":
        print("错误：需要设置 KIWI_MEDIA_BACKEND=s3 才能迁移到对象存储", file=sys.stderr)
        return 2
    root = Path(settings.upload_dir)
    if not root.is_dir():
        print(f"错误：本地上传目录不存在：{root}", file=sys.stderr)
        return 2

    files = _iter_files(root, args.prefix)
    # 迁移必须直接查 S3，不能走 local_fallback，否则本地文件会被误判为已上传。
    store = S3ObjectStore(
        endpoint=settings.s3_endpoint,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        region=settings.s3_region,
        prefix=settings.s3_prefix,
        connect_timeout=settings.s3_connect_timeout,
        read_timeout=settings.s3_read_timeout,
        local_fallback=None,
    )
    uploaded = skipped = failed = 0
    uploaded_bytes = 0
    for path, key in files:
        size = path.stat().st_size
        try:
            existing = await store.stat(key)
        except ObjectStoreError as exc:
            print(f"跳过（无法读取对象信息）：{key}：{exc}", file=sys.stderr)
            failed += 1
            continue
        if not args.overwrite and existing is not None and existing.size == size:
            skipped += 1
            continue
        if args.dry_run:
            uploaded += 1
            uploaded_bytes += size
            if args.verbose:
                print(f"[dry-run] {key} ({size} bytes)")
            continue

        async def chunks():
            import aiofiles

            async with aiofiles.open(path, "rb") as handle:
                while chunk := await handle.read(CHUNK):
                    yield chunk

        try:
            await store.save_stream(
                key, chunks(), content_type=guess_content_type(key)
            )
        except (OSError, ObjectStoreError) as exc:
            print(f"失败：{key}：{exc}", file=sys.stderr)
            failed += 1
            continue
        uploaded += 1
        uploaded_bytes += size
        if args.verbose:
            print(f"已上传 {key} ({size} bytes)")

    print(
        "迁移完成："
        f"上传 {uploaded} 个，跳过 {skipped} 个，失败 {failed} 个，"
        f"共 {uploaded_bytes / (1024 * 1024):.1f} MB"
        + ("（dry-run，未写入）" if args.dry_run else "")
    )
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="把本地 upload_dir 迁移到 S3/MinIO")
    parser.add_argument(
        "--prefix",
        action="append",
        default=None,
        help="只迁移指定前缀（可重复），默认全部；传空字符串表示全部",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    parser.add_argument(
        "--overwrite", action="store_true", help="即使大小一致也重新上传（恢复演练用）"
    )
    parser.add_argument("--verbose", action="store_true", help="逐文件输出")
    args = parser.parse_args()
    if args.prefix is None:
        args.prefix = [""]
    return asyncio.run(_migrate(args))


if __name__ == "__main__":
    raise SystemExit(main())
