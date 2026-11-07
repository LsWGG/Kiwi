"""内置主题：把 Kiwi 当前的默认视觉提炼成可导出、可预览的主题插件。

内置主题不落库，始终随代码发布；用户可以在主题设置里预览、应用或导出
为 zip，再作为自定义主题重新导入。当前只有一套「经典紫」——颜色令牌与
前端默认值完全一致，因此启用后不会改变现有界面。

主题包本身仍然是标准插件包格式（plugin.json + 可选 theme.css +
assets/），与用户导入的主题包共用同一套解析与应用逻辑。
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

BUILTIN_THEMES: tuple[dict[str, Any], ...] = (
    {
        "key": "kiwi-classic",
        "name": "经典紫",
        "version": "1.0.0",
        "description": "Kiwi 默认视觉：清爽浅色面板，编辑模式冷紫、学习模式翠绿。",
        "author": "Kiwi",
        "icon": "palette",
        "homepage": "",
        "theme": {
            "mode": "light",
            # 刻意省略 accent：保留内置的编辑紫 / 学习绿双强调色；
            # 安装的第三方主题会声明自己的 accent，两种模式共用。
            "colors": {
                "app.background": "#f8fafc",
                "surface.background": "#ffffff",
                "surface.muted": "#f1f5f9",
                "surface.strong": "#e2e8f0",
                "border.subtle": "#f1f5f9",
                "border.default": "#e2e8f0",
                "border.strong": "#cbd5e1",
                "text.primary": "#1e293b",
                "text.strong": "#334155",
                "text.secondary": "#475569",
                "text.muted": "#64748b",
                "text.subtle": "#94a3b8",
                "text.faint": "#cbd5e1",
                "accent.foreground": "#ffffff",
            },
            "background": {
                "image": "",
                "size": "cover",
                "position": "center",
                "repeat": "no-repeat",
                "dim": 0,
                "blur": 0,
            },
            "surface": {"opacity": 1, "blur": 0},
            "typography": {"body": "", "heading": "", "mono": ""},
            "preview": "",
        },
        "style": "",
    },
)

BUILTIN_KEYS = {theme["key"] for theme in BUILTIN_THEMES}


def get_builtin(key: str) -> dict[str, Any] | None:
    for theme in BUILTIN_THEMES:
        if theme["key"] == key:
            return theme
    return None


def builtin_manifest(theme: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "kind": "theme",
        "key": theme["key"],
        "name": theme["name"],
        "version": theme["version"],
        "description": theme["description"],
        "author": theme["author"],
        "icon": theme["icon"],
        "homepage": theme["homepage"],
        "entry": "",
        "style": "theme.css" if theme.get("style") else "",
        "blocks": [],
        "theme": theme["theme"],
    }


def _readme(theme: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {theme['name']}",
            "",
            theme["description"],
            "",
            f"- key: `{theme['key']}`",
            f"- version: `{theme['version']}`",
            "- kind: `theme`",
            "",
            "## 安装",
            "",
            "在 Kiwi「设置 → 主题 → 导入主题」中选择本 zip。",
            "主题只包含声明式 JSON 与 CSS，不执行 JavaScript。",
            "",
            "## 开发",
            "",
            "`plugin.json` 的 `theme` 字段定义颜色令牌、背景、透明度与字体；",
            "可选 `theme.css` 补充装饰性样式，`assets/` 存放背景图、预览图与字体。",
            "完整规范见 `docs/THEME_SPEC.md`。",
            "",
        ]
    )


def export_zip(theme: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "plugin.json",
            json.dumps(builtin_manifest(theme), ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr("README.md", _readme(theme))
        if theme.get("style"):
            archive.writestr("theme.css", theme["style"])
    return buffer.getvalue()
