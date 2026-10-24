"""BM25 词法检索与混合融合的纯逻辑测试。"""

from __future__ import annotations

from app.services.lexical import bm25_scores, title_boost, tokenize
from app.services.retrieval import _hit_key, _rrf


def test_tokenize_cjk_bigrams_and_ascii_words():
    tokens = tokenize("PostgreSQL 全文检索 full-text")
    assert "postgresql" in tokens
    assert "full-text" in tokens
    assert "全文" in tokens
    assert "文检" in tokens
    assert "检索" in tokens
    assert "的" not in tokenize("我的笔记")


def test_bm25_ranks_relevant_document_first():
    documents = [
        tokenize("数据库索引可以加速查询"),
        tokenize("今天天气很好，适合散步"),
        tokenize("索引失效通常与类型转换有关"),
    ]
    scores = bm25_scores(tokenize("索引 查询"), documents)
    assert scores[0] > scores[1]
    assert scores[2] > scores[1]
    assert scores[1] == 0


def test_bm25_empty_inputs_are_zero():
    assert bm25_scores([], [tokenize("a b")]) == [0.0]
    assert bm25_scores(tokenize("索引"), []) == []


def test_title_boost_is_bounded():
    tokens = tokenize("数据库索引优化")
    assert title_boost("数据库索引", tokens) > 0
    assert title_boost("数据库索引", tokens) <= 6 * 0.35
    assert title_boost("", tokens) == 0


def test_weighted_rrf_can_downweight_lexical_list():
    dense = [{"id": "a"}, {"id": "b"}]
    lexical = [{"id": "b"}, {"id": "c"}]
    merged = _rrf([dense, lexical], limit=3, weights=[1.0, 0.01])
    assert [item["id"] for item in merged] == ["a", "b", "c"]


def test_hit_key_falls_back_to_payload_anchor():
    assert _hit_key({"payload": {"note_id": "n1", "chunk_index": 2}}) == ":n1:2"
    assert _hit_key({"id": "point-1"}) == "point-1"
