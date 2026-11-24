"""把 S3 / MinIO 中的对象拉回本地 upload_dir（换机 / 恢复演练用）。

当前素材原文件、笔记快照等仍有少量读取路径使用本地 Path；S3 模式会把它们
双写到对象存储。换一台后端机器时，可先执行本脚本把对象落到本地，保证这些
读取路径可用。

运行（在 backend 目录）：

    KIWI_MEDIA_BACKEND=s3 python scripts/rehydrate_storage.py --dry-run
    KIWI_MEDIA_BACKEND=s3 python scripts/rehydrate_storage.py
    KIWI_MEDIA_BACKEND=s3 python scripts/rehydrate_storage.py --prefix media
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
)


async def _rehydrate(args) -> int:
    if settings.media_backend != "s3":
        print("错误：需要 KIWI_MEDIA_BACKEND=s3 才能从对象存储恢复", file=sys.stderr)
        return 2
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
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    items = await store.list(args.prefix or "")
    restored = skipped = failed = 0
    total = 0
    for item in items:
        target = root / item.key
        if not args.overwrite and target.is_file() and target.stat().st_size == item.size:
            skipped += 1
            continue
        if args.dry_run:
            restored += 1
            total += item.size
            if args.verbose:
                print(f"[dry-run] {item.key} ({item.size} bytes)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.part")
        try:
            import aiofiles

            async with aiofiles.open(partial, "wb") as handle:
                async for chunk in store.open(item.key):
                    await handle.write(chunk)
            partial.replace(target)
        except (OSError, ObjectStoreError) as exc:
            partial.unlink(missing_ok=True)
            print(f"失败：{item.key}：{exc}", file=sys.stderr)
            failed += 1
            continue
        restored += 1
        total += item.size
        if args.verbose:
            print(f"已恢复 {item.key} ({item.size} bytes)")
    print(
        "恢复完成："
        f"下载 {restored} 个，跳过 {skipped} 个，失败 {failed} 个，"
        f"共 {total / (1024 * 1024):.1f} MB"
        + ("（dry-run，未写入）" if args.dry_run else "")
    )
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="把 S3/MinIO 对象拉回本地 upload_dir")
    parser.add_argument("--prefix", default="", help="只恢复指定前缀，默认全部")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    parser.add_argument("--overwrite", action="store_true", help="即使大小一致也覆盖")
    parser.add_argument("--verbose", action="store_true", help="逐文件输出")
    args = parser.parse_args()
    return asyncio.run(_rehydrate(args))


if __name__ == "__main__":
    raise SystemExit(main())
