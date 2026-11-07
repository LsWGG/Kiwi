#!/usr/bin/env python3
"""把仓库中的插件 / 主题规范、示例与 skill 同步到后端随镜像分发的资源目录。

开发套件接口 `/api/plugins/dev-kit` 与 `/api/themes/dev-kit` 只读取
``backend/app/resources/plugin_dev_kit``，这样运行时镜像即使只复制 ``backend/``
也能返回完整内容。修改 ``docs/PLUGIN_SPEC.md``、``docs/THEME_SPEC.md``、
``docs/examples/plugins/``、``docs/examples/themes/``、
``.claude/skills/kiwi-plugin/SKILL.md`` 或 ``.claude/skills/kiwi-theme/SKILL.md`` 后运行：

    uv run python scripts/sync_plugin_dev_kit.py
    uv run python scripts/sync_plugin_dev_kit.py --check  # CI 校验是否有漂移

``--check`` 只读，不会写文件；发现差异时返回 1。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
RESOURCE_ROOT = BACKEND_ROOT / "app" / "resources" / "plugin_dev_kit"

SOURCES = (
    (REPO_ROOT / "docs" / "PLUGIN_SPEC.md", RESOURCE_ROOT / "PLUGIN_SPEC.md"),
    (REPO_ROOT / "docs" / "THEME_SPEC.md", RESOURCE_ROOT / "THEME_SPEC.md"),
    (
        REPO_ROOT / ".claude" / "skills" / "kiwi-plugin" / "SKILL.md",
        RESOURCE_ROOT / "skill" / "kiwi-plugin" / "SKILL.md",
    ),
    (
        REPO_ROOT / ".claude" / "skills" / "kiwi-theme" / "SKILL.md",
        RESOURCE_ROOT / "skill" / "kiwi-theme" / "SKILL.md",
    ),
)

EXAMPLE_DIRS = ("plugins", "themes")


def _example_sources(subdir: str) -> list[tuple[Path, Path]]:
    source = REPO_ROOT / "docs" / "examples" / subdir
    target = RESOURCE_ROOT / "examples" / subdir
    return [
        (path, target / path.relative_to(source))
        for path in sorted(source.rglob("*"))
        if path.is_file()
    ]


def _pairs() -> list[tuple[Path, Path]]:
    pairs = list(SOURCES)
    for subdir in EXAMPLE_DIRS:
        pairs.extend(_example_sources(subdir))
    return pairs


def _drift() -> list[str]:
    problems: list[str] = []
    for source, target in _pairs():
        if not source.is_file():
            problems.append(f"源文件缺失：{source.relative_to(REPO_ROOT)}")
        elif not target.is_file():
            problems.append(f"资源缺失：{target.relative_to(BACKEND_ROOT)}")
        elif not filecmp.cmp(source, target, shallow=False):
            problems.append(f"内容不同：{target.relative_to(BACKEND_ROOT)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查，不写入")
    args = parser.parse_args()

    if args.check:
        problems = _drift()
        if problems:
            print("插件开发套件资源与仓库源不一致：", file=sys.stderr)
            for item in problems:
                print(f"  - {item}", file=sys.stderr)
            print("运行 uv run python scripts/sync_plugin_dev_kit.py 同步。", file=sys.stderr)
            return 1
        print("插件开发套件资源已同步。")
        return 0

    for source, target in _pairs():
        if not source.is_file():
            print(f"跳过缺失的源文件：{source}", file=sys.stderr)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(f"同步 {source.relative_to(REPO_ROOT)} → {target.relative_to(BACKEND_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
