"""标题层级感知的分块器（非固定 token）。

原则：
- 以 Markdown 标题（# / ## …）为 chunk 锚点；无标题的正文段落独立成块；
- 正文按 ~800 中文字符软边界 + 50 字符重叠滑窗，避免打断语义；
- 按 Unicode 字符计数，不按半角 token。
"""

from __future__ import annotations

import re

# 目标块长与重叠
CHUNK_SIZE = 800
OVERLAP = 50

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def _split_long_text(text: str) -> list[str]:
    """把超长正文切成 <=CHUNK_SIZE 的片段，带重叠。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        # 软边界：尝试在句末切开
        if end < len(text):
            window = text[start + CHUNK_SIZE - 80 : end + 80]
            # 找最近的句末标点
            for sep in ("。", "！", "？", "\n", "；", "．"):
                idx = window.rfind(sep)
                # 只在窗口的「末尾 20 字」内切分：既保留足够上下文，
                # 又保证 chunk 不超过 CHUNK_SIZE。
                if 60 <= idx < 80:
                    end = start + CHUNK_SIZE - 80 + idx + 1
                    break
        seg = text[start:end]
        if seg:
            chunks.append(seg.strip())
        if end >= len(text):
            break
        start = max(end - OVERLAP, start + 1)
    return [c for c in chunks if c]


def split_markdown(text: str) -> list[dict]:
    """把 Markdown/纯文本切成 [{title, heading_level, content}]。

    返回带结构化元数据的块，供嵌入与检索。
    """
    if not text.strip():
        return []
    lines = text.splitlines()
    blocks: list[dict] = []
    current_heading: str | None = None
    current_level: int = 0
    buffer: list[str] = []

    def flush():
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(
                {
                    "title": current_heading or f"片段 {len(blocks) + 1}",
                    "heading_level": current_level or 0,
                    "content": body,
                }
            )
        buffer = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if m and line.startswith("#"):
            flush()
            current_heading = m.group(2).strip()
            current_level = len(m.group(1))
            # 标题自身也作为一个可检索单元（若后面无内容）
            buffer = []
            if current_heading:
                buffer.append(line)
            continue
        # 非 heading 行
        if not current_heading and not line.strip():
            flush()
            continue
        buffer.append(line)

    flush()

    # 将超长块二次切分
    out: list[dict] = []
    for b in blocks:
        for seg in _split_long_text(b["content"]):
            out.append({**b, "content": seg})
    return out


def split_text(text: str) -> list[str]:
    """简化接口：返回纯文本块（无元数据）。"""
    return [b["content"] for b in split_markdown(text)]
