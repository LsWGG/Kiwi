"""轻量 BM25 词法检索。

中文没有空格分词，这里用「汉字连续串 → 二元组（bigram）+ 单字」的
兜底方案：无需引入 jieba 之类的重依赖，也能覆盖「数据库索引」这类短语。
ASCII / 数字按整词处理，保留 ``gpt-4``、``0.2.0`` 这类版本号。

BM25 只负责把「词面完全匹配」的分块排到前面，最终名次仍由 RRF 与向量
召回融合，因此分词质量不需要达到搜索引擎级别。
"""

from __future__ import annotations

import math
import re
from collections import Counter

# ASCII 单词 / 数字 / 版本号：字母开头，允许内部 . _ - + #
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._+#-]*")
# 连续 CJK（含日韩统一表意文字）；中间夹空格时会被拆成多个串。
_CJK_RUN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")

_STOPWORDS = {
    "的",
    "了",
    "和",
    "与",
    "或",
    "在",
    "是",
    "有",
    "及",
    "对",
    "中",
    "上",
    "下",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
}


def tokenize(text: str) -> list[str]:
    """把文本切成可比较的检索词。

    重复词会保留：BM25 需要词频（TF）。
    """
    if not text:
        return []
    lowered = text.lower()
    tokens: list[str] = []

    for match in _ASCII_TOKEN_RE.finditer(lowered):
        token = match.group(0).strip("._-+#")
        if len(token) >= 2 and token not in _STOPWORDS:
            tokens.append(token)

    for match in _CJK_RUN_RE.finditer(lowered):
        run = match.group(0)
        # 单字仅在孤立成串时保留，避免长句被上万个单字噪声淹没。
        if len(run) == 1:
            if run not in _STOPWORDS:
                tokens.append(run)
            continue
        if run in _STOPWORDS:
            continue
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in _STOPWORDS:
                tokens.append(bigram)
    return tokens


def _idf(doc_count: int, df: int) -> float:
    return math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))


def bm25_scores(
    query_tokens: list[str],
    documents: list[list[str]],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """对一组已分词的文档计算 BM25 分数。

    ``documents[i]`` 是第 i 篇文档的词列表；返回与之一一对应的分数。
    """
    if not query_tokens or not documents:
        return [0.0 for _ in documents]

    doc_count = len(documents)
    lengths = [len(doc) for doc in documents]
    avg_len = sum(lengths) / doc_count if doc_count else 0.0
    # 同一查询词只计一次，词频完全交给文档侧统计。
    unique_terms = list(dict.fromkeys(query_tokens))
    doc_freq: Counter[str] = Counter()
    term_freqs = [Counter(doc) for doc in documents]
    for tf in term_freqs:
        for term in unique_terms:
            if tf.get(term):
                doc_freq[term] += 1

    scores: list[float] = []
    for i, tf in enumerate(term_freqs):
        norm = 1.0 - b + (b * lengths[i] / avg_len if avg_len else 0.0)
        score = 0.0
        for term in unique_terms:
            freq = tf.get(term, 0)
            if not freq:
                continue
            score += _idf(doc_count, doc_freq[term]) * (
                freq * (k1 + 1.0) / (freq + k1 * norm)
            )
        scores.append(round(score, 6))
    return scores


def title_boost(title: str, query_tokens: list[str]) -> float:
    """标题命中给固定加成，避免相关标题被正文长分块淹没。"""
    if not title or not query_tokens:
        return 0.0
    title_tokens = set(tokenize(title))
    if not title_tokens:
        return 0.0
    hits = sum(1 for term in dict.fromkeys(query_tokens) if term in title_tokens)
    return min(hits, 6) * 0.35
