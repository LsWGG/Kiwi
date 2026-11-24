"""Agent 确定性快路径。

URL / 空白模板这类任务在读完工具结果后已经具备生成写操作所需的全部材料，
不需要再让模型把同一份正文复述一遍。快路径只负责合成待确认的
``create_note`` 动作；是否执行仍由用户确认，权限与普通工具调用完全一致。

命中条件刻意收得很窄，任何需要总结、改写、填写内容或指定分组的请求都会
回退到正常 Agent 循环，避免快路径覆盖用户的真实意图。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_SAVE_NOTE_RE = re.compile(
    r"(新建|创建|保存|存为|整理成|整理为|写入|收藏).{0,12}笔记"
    r"|笔记.{0,12}(新建|创建|保存|收藏)"
)
_TRANSFORM_WORDS = (
    "总结",
    "摘要",
    "提炼",
    "概括",
    "改写",
    "翻译",
    "精简",
    "润色",
    "大纲",
    "要点",
    "分析",
    "评价",
    "解读",
    "摘录",
    "改写为",
)
_FOLDER_WORDS = ("目录", "分组", "文件夹")
_TEMPLATE_GENERATE_WORDS = (
    "生成",
    "规划",
    "填写",
    "根据",
    "按照",
    "内容",
    "写一篇",
    "撰写",
    "整理",
    "扩写",
    "填充",
)


def _has_folder_target(query: str) -> bool:
    # 「根目录」是允许的默认目标；其余目录 / 分组需要模型解析 ID。
    stripped = query.replace("知识库根目录", "").replace("根目录", "")
    return any(word in stripped for word in _FOLDER_WORDS)


def _safe_title(value: Any, fallback: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    return (title or fallback)[:300]


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        text = line.strip().lstrip("#").strip()
        if text and line.strip().startswith("#"):
            return text[:300]
    return ""


def _append_source(markdown: str, url: str) -> str:
    if not url or url in markdown:
        return markdown
    return f"{markdown.rstrip()}\n\n---\n\n> 来源：{url}\n"


def build_after_read_tool(
    query: str,
    tool: str,
    result: dict[str, Any],
    *,
    can_write: bool,
    plan: list[dict],
) -> dict[str, Any] | None:
    """根据上一个只读工具的结果合成 ``create_note`` 动作；不适用时返回 None。"""
    if not can_write or not query or not isinstance(result, dict):
        return None
    if result.get("ok") is False:
        return None
    if _has_folder_target(query):
        return None
    if any(word in query for word in _TRANSFORM_WORDS):
        return None

    if tool == "fetch_url":
        if not _SAVE_NOTE_RE.search(query):
            return None
        if result.get("markdown_truncated"):
            return None
        markdown = str(result.get("markdown") or "").strip()
        if not markdown:
            return None
        title = _safe_title(
            result.get("title"),
            _first_heading(markdown) or "网页笔记",
        )
        body = _append_source(markdown, str(result.get("final_url") or result.get("url") or ""))
        return {
            "tool": "create_note",
            "args": {"title": title, "body_md": body},
            "summary": f"新建笔记《{title}》（使用网页正文）",
            "step": 2 if len(plan) >= 2 else None,
            "thought": "网页正文已读取，直接使用正文新建笔记。",
        }

    if tool == "get_template":
        if "模板" not in query or result.get("body_truncated"):
            return None
        if not any(word in query for word in ("新建", "创建", "套用")):
            return None
        name = str(result.get("name") or "模板")
        # 模板名本身可能含「规划」等词（如「旅游规划」）；判断生成意图时先去掉。
        intent_text = query.replace(name, "")
        if any(word in intent_text for word in _TEMPLATE_GENERATE_WORDS):
            return None
        body = str(result.get("body_md") or "").strip()
        if not body:
            return None
        pattern = str(result.get("title_pattern") or "").strip()
        title = (
            pattern.replace("{{date}}", datetime.now().strftime("%Y-%m-%d")).strip()
            or f"{name} 笔记"
        )
        args: dict[str, Any] = {"title": title[:300], "body_md": body}
        tags = [str(tag) for tag in result.get("tags") or [] if str(tag).strip()]
        if tags:
            args["tags"] = tags[:30]
        return {
            "tool": "create_note",
            "args": args,
            "summary": f"按模板《{name}》新建笔记",
            "step": 2 if len(plan) >= 2 else None,
            "thought": "模板正文已读取，直接套用模板新建空白笔记。",
        }

    return None


__all__ = ["build_after_read_tool"]
