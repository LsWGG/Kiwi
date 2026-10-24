"""编辑器内置扩展组件注册表与启停状态。

这些组件随前端一起发布（日期、公式、文本绘图、图册、分栏、日历、数据表、
待办进度），设置页与编辑器共用同一份后端清单，停用后工具栏「扩展组件」菜单
与斜杠菜单同步移除对应入口。

每个内置组件同时带一份「内置包」描述（kind=builtin）：可导出为 zip，用于
审阅组件能力、分享配置，或作为开发同效果组件插件的参考。内置包不包含可独立
执行的 JS，也不会通过第三方插件导入接口安装。
"""

from __future__ import annotations

import base64
import json
from typing import Any

from app.db.models import SystemSettings

# 顺序与编辑器「+ → 扩展组件」面板保持一致。
BUILTIN_EXTENSIONS: tuple[dict[str, str], ...] = (
    {
        "key": "date",
        "label": "日期",
        "hint": "可点击修改的日期胶囊",
        "icon": "calendar",
    },
    {
        "key": "formula",
        "label": "公式",
        "hint": "KaTeX 数学公式",
        "icon": "hash",
    },
    {
        "key": "mermaid",
        "label": "文本绘图",
        "hint": "Mermaid 流程图 / 时序图",
        "icon": "graph",
    },
    {
        "key": "gallery",
        "label": "图册",
        "hint": "多图网格 / 滑动展示",
        "icon": "gallery",
    },
    {
        "key": "columns2",
        "label": "分栏卡片 · 2 栏",
        "hint": "左右并排的富文本",
        "icon": "columns",
    },
    {
        "key": "columns3",
        "label": "分栏卡片 · 3 栏",
        "hint": "三栏并排的富文本",
        "icon": "columns",
    },
    {
        "key": "calendar",
        "label": "日历",
        "hint": "月视图，可为日期添加安排",
        "icon": "calendar",
    },
    {
        "key": "datatable",
        "label": "数据表",
        "hint": "可增删行列，支持批量粘贴",
        "icon": "table",
    },
    {
        "key": "taskProgress",
        "label": "待办进度",
        "hint": "绑定附近任务清单，实时统计完成度",
        "icon": "checkSquare",
    },
)

KEYS: tuple[str, ...] = tuple(item["key"] for item in BUILTIN_EXTENSIONS)

# 导出内置包时补充的节点 / Markdown / 示例属性信息。
BUILTIN_PACKAGE_META: dict[str, dict[str, Any]] = {
    "date": {
        "node": "kiwiDate",
        "language": "",
        "sample_props": {"date": "2026-10-23"},
        "source_files": ("date.ts", "DateNodeView.vue"),
    },
    "formula": {
        "node": "kiwiFormula",
        "language": "kiwi-math",
        "sample_props": {"latex": "E = mc^2"},
        "source_files": ("formula.ts", "FormulaNodeView.vue"),
    },
    "mermaid": {
        "node": "kiwiMermaid",
        "language": "mermaid",
        "sample_props": {
            "code": "flowchart LR\n  A[需求] --> B[开发] --> C[验收]"
        },
        "source_files": ("mermaid.ts", "MermaidNodeView.vue"),
    },
    "gallery": {
        "node": "kiwiGallery",
        "language": "kiwi-gallery",
        "sample_props": {"images": [], "columns": 3, "layout": "grid"},
        "source_files": ("gallery.ts", "GalleryNodeView.vue"),
    },
    "columns2": {
        "node": "kiwiColumns",
        "language": "",
        "sample_props": {"count": 2},
        "source_files": ("columns.ts",),
    },
    "columns3": {
        "node": "kiwiColumns",
        "language": "",
        "sample_props": {"count": 3},
        "source_files": ("columns.ts",),
    },
    "calendar": {
        "node": "kiwiCalendar",
        "language": "kiwi-calendar",
        "sample_props": {"month": "", "events": [], "title": "日历"},
        "source_files": ("calendar.ts", "CalendarNodeView.vue"),
    },
    "datatable": {
        "node": "kiwiDataTable",
        "language": "kiwi-datatable",
        "sample_props": {"title": "示例数据表", "fields": [], "views": [], "rows": []},
        "source_files": ("dataTable.ts", "dataTableModel.ts", "DataTableNodeView.vue"),
    },
    "taskProgress": {
        "node": "kiwiTaskProgress",
        "language": "kiwi-task-progress",
        "sample_props": {
            "label": "待办进度",
            "showCount": True,
            "showPercent": True,
            "color": "indigo",
            "bind": "auto",
        },
        "source_files": ("taskProgress.ts", "TaskProgressNodeView.vue"),
    },
}


def _sample_image(title: str, start: str, end: str) -> str:
    """生成内置图册预览用的渐变示例图（随包内联，不依赖外网）。"""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{start}"/>'
        f'<stop offset="1" stop-color="{end}"/>'
        "</linearGradient></defs>"
        '<rect width="800" height="500" fill="url(#g)"/>'
        '<circle cx="640" cy="120" r="150" fill="rgba(255,255,255,.18)"/>'
        '<circle cx="180" cy="410" r="120" fill="rgba(255,255,255,.12)"/>'
        '<text x="60" y="270" font-family="sans-serif" font-size="54" '
        f'font-weight="600" fill="white">{title}</text>'
        "</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _fenced(language: str, payload: str) -> str:
    return f"```{language}\n{payload}\n```"


_GALLERY_SAMPLE = {
    "columns": 3,
    "layout": "grid",
    "images": [
        {
            "url": _sample_image("需求洞察", "#6366f1", "#a855f7"),
            "caption": "需求洞察",
        },
        {
            "url": _sample_image("设计协作", "#0ea5e9", "#22d3ee"),
            "caption": "设计协作",
        },
        {
            "url": _sample_image("发布上线", "#f59e0b", "#ef4444"),
            "caption": "发布上线",
        },
    ],
}

_DATATABLE_SAMPLE = {
    "title": "项目排期",
    "fields": [
        {"id": "name", "name": "事项", "type": "text"},
        {
            "id": "status",
            "name": "状态",
            "type": "select",
            "options": [
                {"id": "todo", "name": "待办", "color": "slate"},
                {"id": "doing", "name": "进行中", "color": "blue"},
                {"id": "done", "name": "已完成", "color": "green"},
            ],
        },
        {"id": "date", "name": "日期", "type": "date"},
    ],
    "views": [
        {"id": "table", "name": "表格", "type": "table", "hidden_fields": []},
    ],
    "rows": [
        {
            "id": "r1",
            "data": {"name": "需求评审", "status": "done", "date": "2026-10-21"},
        },
        {
            "id": "r2",
            "data": {"name": "组件开发", "status": "doing", "date": "2026-10-23"},
        },
        {
            "id": "r3",
            "data": {"name": "回归测试", "status": "todo", "date": "2026-10-27"},
        },
    ],
    "view": "table",
}

_CALENDAR_SAMPLE = {
    "month": "2026-10",
    "title": "十月安排",
    "events": [
        {
            "id": "e1",
            "title": "组件开发",
            "start": "2026-10-21",
            "end": "2026-10-23",
            "color": "blue",
        },
        {
            "id": "e2",
            "title": "方案评审",
            "start": "2026-10-26",
            "end": "2026-10-26",
            "color": "amber",
        },
        {
            "id": "e3",
            "title": "发布上线",
            "start": "2026-10-29",
            "end": "2026-10-30",
            "color": "green",
        },
    ],
}

_COLUMNS_SAMPLE = (
    "> [!COLUMNS]\n"
    ">\n"
    "> [!COLUMN]\n"
    ">\n"
    "> **左栏**\n"
    ">\n"
    "> 适合对比说明、图文并排。\n"
    ">\n"
    "> [!COLUMN]\n"
    ">\n"
    "> **右栏**\n"
    ">\n"
    "> 每栏都是完整富文本，可插入列表与图片。"
)

BUILTIN_PREVIEW_MARKDOWN: dict[str, str] = {
    "date": "创建于 📅 2026-10-23，点击日期胶囊即可修改。",
    "formula": _fenced("kiwi-math", "E = mc^2"),
    "mermaid": _fenced(
        "mermaid",
        "flowchart LR\n  A[需求] --> B[开发] --> C[验收]",
    ),
    "gallery": _fenced(
        "kiwi-gallery",
        json.dumps(_GALLERY_SAMPLE, ensure_ascii=False),
    ),
    "columns2": _COLUMNS_SAMPLE,
    "columns3": (
        _COLUMNS_SAMPLE
        + "\n>\n> [!COLUMN]\n>\n> **第三栏**\n>\n> 三栏布局适合并排展示三个要点。"
    ),
    "calendar": _fenced(
        "kiwi-calendar",
        json.dumps(_CALENDAR_SAMPLE, ensure_ascii=False),
    ),
    "datatable": _fenced(
        "kiwi-datatable",
        json.dumps(_DATATABLE_SAMPLE, ensure_ascii=False),
    ),
    "taskProgress": (
        _fenced(
            "kiwi-task-progress",
            json.dumps(
                {
                    "label": "本周待办",
                    "showCount": True,
                    "showPercent": True,
                    "color": "indigo",
                    "bind": "auto",
                },
                ensure_ascii=False,
            ),
        )
        + "\n\n- [x] 需求评审\n- [ ] 组件开发\n- [ ] 回归测试"
    ),
}


def builtin_meta(key: str) -> dict[str, Any]:
    item = next((entry for entry in BUILTIN_EXTENSIONS if entry["key"] == key), None)
    if item is None:
        raise KeyError(key)
    return {**item, **BUILTIN_PACKAGE_META.get(key, {})}


def builtin_package(key: str) -> dict[str, Any]:
    """生成可导出的内置包 manifest（kind=builtin，不可作为第三方代码插件导入）。"""
    item = builtin_meta(key)
    return {
        "manifest_version": 1,
        "kind": "builtin",
        "key": f"kiwi-builtin-{key}",
        "builtin": key,
        "name": item["label"],
        "version": "1.0.0",
        "description": item["hint"],
        "author": "Kiwi",
        "icon": item["icon"],
        "homepage": "",
        "entry": "",
        "style": "",
        "blocks": [
            {
                "type": key,
                "label": item["label"],
                "icon": item["icon"],
                "description": item["hint"],
                "category": "内置扩展组件",
                "template_markdown": "",
                "default_props": item.get("sample_props", {}),
                "node": item.get("node", ""),
                "markdown_language": item.get("language", ""),
            }
        ],
        "runtime": {
            "builtin": key,
            "node": item.get("node", ""),
            "markdown_language": item.get("language", ""),
            "source_files": list(item.get("source_files", ())),
        },
        "settings": [],
    }


def builtin_readme(key: str) -> str:
    item = builtin_meta(key)
    sources = "\n".join(
        f"- `frontend/src/components/editor/extensions/{name}`"
        for name in item.get("source_files", ())
    )
    return (
        f"# 内置扩展组件：{item['label']}\n\n"
        f"{item['hint']}\n\n"
        "这是 Kiwi 应用随附的内置组件包描述，**不包含可独立安装的 JavaScript**。\n"
        "导出用于审阅组件能力、分享配置，或作为开发同效果第三方组件插件的参考。\n\n"
        f"- builtin key: `{key}`\n"
        f"- Tiptap node: `{item.get('node', '')}`\n"
        f"- Markdown: "
        f"{f'```{item.get('language')} 围栏 + JSON' if item.get('language') else '行内节点'}\n\n"
        "## 源码位置\n\n"
        f"{sources}\n\n"
        "## 开发第三方组件插件\n\n"
        "如果要实现类似交互，可参考 Kiwi 设置页「插件开发规范」或开发套件中的\n"
        "`docs/PLUGIN_SPEC.md` 与 `docs/examples/plugins/`（counter / pomodoro / countdown）。\n"
    )


def disabled_from_row(row: SystemSettings | None) -> list[str]:
    """读取停用集合：忽略历史遗留或已下线的未知 key，保持注册表顺序。"""
    if row is None:
        return []
    raw = row.editor_disabled_extensions or []
    disabled = {str(key) for key in raw if isinstance(key, str)}
    return [key for key in KEYS if key in disabled]


def normalize_disabled(keys: list[str]) -> list[str]:
    """去重并拒绝未知 key（调用方负责转成 400）。"""
    unknown = sorted({key for key in keys if key not in KEYS})
    if unknown:
        raise ValueError(f"未知的扩展组件：{', '.join(unknown)}")
    wanted = set(keys)
    return [key for key in KEYS if key in wanted]


def _items(disabled: list[str]) -> list[dict[str, Any]]:
    disabled_set = set(disabled)
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "hint": item["hint"],
            "icon": item["icon"],
            "group": "扩展组件",
            "enabled": item["key"] not in disabled_set,
            "preview_markdown": BUILTIN_PREVIEW_MARKDOWN.get(item["key"], ""),
        }
        for item in BUILTIN_EXTENSIONS
    ]


def payload(row: SystemSettings | None) -> dict[str, Any]:
    disabled = disabled_from_row(row)
    items = _items(disabled)
    return {
        "items": items,
        "enabled": [item["key"] for item in items if item["enabled"]],
        "disabled": disabled,
    }
