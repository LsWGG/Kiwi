"""检索融合与 Markdown 分块器的纯逻辑测试。"""

from __future__ import annotations

from app.services.retrieval import _cosine_merge, _rrf
from app.services.splitter import CHUNK_SIZE, _split_long_text, split_markdown


def hit(key: str, score: float = 0.0) -> dict:
    return {"id": key, "raw_score": score, "title": key}


def test_rrf_prefers_document_appearing_in_both_lists():
    merged = _rrf([[hit("a"), hit("b")], [hit("b"), hit("c")]], limit=3)
    assert [item["id"] for item in merged] == ["b", "a", "c"]
    assert merged[0]["score"] > merged[1]["score"]
    assert merged[0]["rank"] == 1


def test_rrf_dedupes_same_id_and_keeps_first_payload():
    merged = _rrf([[{**hit("a"), "title": "first"}], [{**hit("a"), "title": "second"}]])
    assert len(merged) == 1
    assert merged[0]["title"] == "first"
    assert len(merged[0]["_ranks"]) == 2


def test_cosine_merge_sorts_and_dedupes():
    merged = _cosine_merge(
        [[hit("a", 0.2), hit("b", 0.9)], [hit("b", 0.8), hit("c", 0.5)]], limit=2
    )
    assert [item["id"] for item in merged] == ["b", "c"]
    assert merged[0]["score"] == 0.9


def test_split_long_text_empty_and_boundaries():
    assert _split_long_text("   ") == []
    text = "第一段。" * 400
    chunks = _split_long_text(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= CHUNK_SIZE for chunk in chunks)
    assert "".join(chunk[:20] for chunk in chunks[:2])


def test_split_markdown_preserves_heading_structure():
    blocks = split_markdown("# 一级\n正文 A\n\n## 二级\n正文 B\n\n无标题段落")
    titles = [(b["heading_level"], b["title"]) for b in blocks]
    assert (1, "一级") in titles
    assert (2, "二级") in titles
    assert any("无标题段落" in b["content"] for b in blocks)
    assert all(b["content"].strip() for b in blocks)

    plain = split_markdown("只有一段没有标题的正文")
    assert len(plain) == 1
    assert plain[0]["heading_level"] == 0


def test_split_markdown_empty():
    assert split_markdown("") == []
    assert split_markdown("   \n\n") == []
