"""插件开发套件资源：必须随后端镜像分发，并与仓库示例保持同步。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dev_kit_resources_match_repo_sources():
    # 运行时镜像只复制 backend/，没有 docs/ 与 .claude/，此时跳过漂移校验；
    # 仓库内跑测试时必须保证 backend/app/resources/plugin_dev_kit 已同步。
    if not (REPO_ROOT / "docs" / "PLUGIN_SPEC.md").is_file():
        pytest.skip("当前环境没有仓库 docs/，跳过开发套件同步校验")
    result = subprocess.run(
        [sys.executable, "scripts/sync_plugin_dev_kit.py", "--check"],
        cwd=REPO_ROOT / "backend",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
