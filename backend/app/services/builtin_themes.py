"""内置主题：随代码发布的「经典紫」与「极光」。

内置主题不落库，始终随代码发布；用户可以在主题设置里预览、应用或导出
为 zip，再作为自定义主题重新导入。默认只有两套：

- 经典紫：颜色令牌与前端默认值完全一致，启用后不会改变现有界面；
- 极光：深色渐变主题，样式、背景与预览图随后端资源一起打包。

主题包本身仍然是标准插件包格式（plugin.json + 可选 theme.css +
assets/），与用户导入的主题包共用同一套解析与应用逻辑。
"""

from __future__ import annotations

import io
import json
import mimetypes
import zipfile
from pathlib import Path
from typing import Any

# 内置主题的静态资源：backend/app/resources/builtin_themes/<key>/
RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "builtin_themes"

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
        "assets": (),
    },
    {
        "key": "aurora",
        "name": "极光",
        "version": "1.0.1",
        "description": "深色极光渐变主题：冷色玻璃面板与青绿强调色。",
        "author": "Kiwi",
        "icon": "sparkle",
        "homepage": "",
        "theme": {
            "mode": "dark",
            "colors": {
                "app.background": "#0b1020",
                "surface.background": "#121a30",
                "surface.muted": "#1a2540",
                "surface.strong": "#253356",
                "border.subtle": "#1c2742",
                "border.default": "#2a3a5e",
                "border.strong": "#3b4f7a",
                "text.primary": "#e7ecff",
                "text.strong": "#d3ddfc",
                "text.secondary": "#b1bfe8",
                "text.muted": "#8b9bc4",
                "text.subtle": "#6f7fa8",
                "text.faint": "#56668c",
                "accent": "#5eead4",
                "accent.foreground": "#062a25",
            },
            "background": {
                "image": "assets/aurora.svg",
                "size": "cover",
                "position": "center",
                "repeat": "no-repeat",
                "dim": 0.25,
                "blur": 2,
            },
            "surface": {"opacity": 0.82, "blur": 14},
            "typography": {
                "body": "",
                "heading": "",
                "mono": "ui-monospace, SFMono-Regular, Menlo, monospace",
            },
            "preview": "assets/preview.svg",
        },
        "style": "theme.css",
        "assets": ("assets/aurora.svg", "assets/preview.svg"),
    },
)

BUILTIN_KEYS = {theme["key"] for theme in BUILTIN_THEMES}


def get_builtin(key: str) -> dict[str, Any] | None:
    for theme in BUILTIN_THEMES:
        if theme["key"] == key:
            return theme
    return None


def _theme_root(theme: dict[str, Any]) -> Path:
    return (RESOURCE_ROOT / theme["key"]).resolve()


def _asset_path(theme: dict[str, Any], relative: str) -> Path:
    """把主题内相对路径解析到资源目录，拒绝越界路径。"""
    root = _theme_root(theme)
    candidate = (root / relative.replace("\\", "/").lstrip("/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("主题资源路径非法")
    return candidate


def asset_paths(theme: dict[str, Any]) -> tuple[str, ...]:
    return tuple(theme.get("assets") or ())


def read_style(theme: dict[str, Any]) -> str:
    name = str(theme.get("style") or "").strip()
    if not name:
        return ""
    return _asset_path(theme, name).read_text(encoding="utf-8")


def read_asset(theme: dict[str, Any], relative: str) -> bytes:
    return _asset_path(theme, relative).read_bytes()


def asset_media_type(relative: str) -> str:
    media_type, _ = mimetypes.guess_type(relative)
    if media_type:
        return media_type
    if relative.endswith(".woff2"):
        return "font/woff2"
    return "application/octet-stream"


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
            archive.writestr("theme.css", read_style(theme))
        for relative in asset_paths(theme):
            archive.writestr(relative, read_asset(theme, relative))
    return buffer.getvalue()
