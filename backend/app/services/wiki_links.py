"""Wiki / 笔记双向链接解析。

Markdown 正文里的行内代码与围栏代码块经常包含 ``[[示例]]`` 这类语法说明，
它们不是真实链接。所有抽取 ``[[...]]`` 的代码先经过 :func:`strip_code`，
避免把文档里的示例当成死链或建立幽灵关联。
"""

from __future__ import annotations

import re

WIKI_LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _strip_inline_code(line: str) -> str:
    """移除一行中的行内代码跨度（成对的反引号串）。"""
    out: list[str] = []
    i = 0
    length = len(line)
    while i < length:
        if line[i] != "`":
            out.append(line[i])
            i += 1
            continue
        run_end = i
        while run_end < length and line[run_end] == "`":
            run_end += 1
        run = run_end - i
        cursor = run_end
        closing = -1
        while cursor < length:
            if line[cursor] != "`":
                cursor += 1
                continue
            close_end = cursor
            while close_end < length and line[close_end] == "`":
                close_end += 1
            if close_end - cursor == run:
                closing = cursor
                break
            cursor = close_end
        if closing < 0:
            # 未闭合的反引号按普通文本处理。
            out.append(line[i:run_end])
            i = run_end
        else:
            out.append(" ")
            i = closing + run
    return "".join(out)


def strip_code(text: str) -> str:
    """把围栏代码块与行内代码替换为空白，保留原有行数。"""
    lines = (text or "").splitlines()
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for line in lines:
        match = _FENCE_OPEN_RE.match(line)
        if fence is None:
            if match:
                fence = (match.group(1)[0], len(match.group(1)))
                out.append("")
                continue
            out.append(_strip_inline_code(line))
            continue
        # 围栏内：只有同字符、长度不小于开启标记且无其它内容的行才关闭。
        if (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= fence[1]
            and not match.group(2).strip()
        ):
            fence = None
        out.append("")
    return "\n".join(out)


def extract_links(text: str) -> list[str]:
    """提取正文中的真实 ``[[链接]]``（忽略代码示例）。"""
    return WIKI_LINK_RE.findall(strip_code(text))
