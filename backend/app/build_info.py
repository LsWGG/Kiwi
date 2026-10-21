"""构建信息：版本、提交号与启动时间。

生产镜像不包含 .git；构建时通过 ``KIWI_BUILD_COMMIT`` / ``KIWI_BUILD_TIME``
注入。本地开发直接读取 ``git rev-parse``，便于和前端 build-info.json 对比。
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache

from app.config import settings

APP_VERSION = "0.2.0"
STARTED_AT = datetime.now(timezone.utc)


@lru_cache
def git_commit() -> str:
    if settings.build_commit:
        return settings.build_commit.strip()
    env_commit = os.environ.get("KIWI_GIT_COMMIT", "").strip()
    if env_commit:
        return env_commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=settings.upload_dir.parent.parent,  # backend/ 或仓库根
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def build_time() -> str:
    if settings.build_time:
        return settings.build_time
    commit_time = git_commit_time()
    return commit_time or ""


@lru_cache
def git_commit_time() -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=settings.upload_dir.parent.parent,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def info() -> dict:
    return {
        "name": "Kiwi",
        "version": APP_VERSION,
        "commit": git_commit(),
        "built_at": build_time(),
        "started_at": STARTED_AT.isoformat(),
    }
