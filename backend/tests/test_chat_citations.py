"""引用锚点的纯逻辑测试。"""

from __future__ import annotations

from app.routers.chat import _first_heading, _plain_excerpt, _quote_from_chunk


def test_plain_excerpt_strips_markdown_noise():
    text = "## 记录\n\n| 名称 | 状态 |\n| --- | --- |\n| 索引优化 | 完成 |\n\n[链接](https://x.test)"
    plain = _plain_excerpt(text)
    assert "#" not in plain
    assert "|" not in plain
    assert "https://" not in plain
    assert "索引优化" in plain


def test_quote_from_chunk_centers_on_query_term():
    body = "前言" * 80 + "数据库索引失效通常与隐式类型转换有关" + "后记" * 80
    quote = _quote_from_chunk(body, "索引")
    assert "索引" in quote
    assert len(quote) <= 180


def test_quote_from_chunk_falls_back_to_prefix():
    quote = _quote_from_chunk("一段与问题无关但需要展示的正文内容", "完全不存在")
    assert quote.startswith("一段与问题无关")


def test_first_heading_returns_deepest_first_heading():
    assert _first_heading("正文\n\n### 小节标题\n内容") == "小节标题"
    assert _first_heading("没有标题") == ""
