"""Anki `.apkg` 导出。

生成 Anki 仍可导入的 schema 11 集合：zip 内写 ``collection.anki2`` 与
``media``，不依赖额外的第三方包。每道 Kiwi 题目输出为一张「正面题干 /
背面答案」卡片，可按题型或知识点拆成子牌组。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Mapping

MODEL_ID = 1_760_000_000_000
MODEL_NAME = "Kiwi 基础"
DECK_ID_BASE = 1_760_000_000_100
FIELD_SEP = "\x1f"

QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
    "case_analysis": "案例分析",
    "essay": "论文题",
}
DIFFICULTY_LABELS = {"basic": "基础", "medium": "进阶", "hard": "挑战"}
GROUP_BY_VALUES = {"none", "type", "topic"}

SCHEMA = """
CREATE TABLE col (
    id integer primary key, crt integer not null, mod integer not null,
    scm integer not null, ver integer not null, dty integer not null,
    usn integer not null, ls integer not null, conf text not null,
    models text not null, decks text not null, dconf text not null,
    tags text not null
);
CREATE TABLE notes (
    id integer primary key, guid text not null, mid integer not null,
    mod integer not null, usn integer not null, tags text not null,
    flds text not null, sfld integer not null, csum integer not null,
    flags integer not null, data text not null
);
CREATE TABLE cards (
    id integer primary key, nid integer not null, did integer not null,
    ord integer not null, mod integer not null, usn integer not null,
    type integer not null, queue integer not null, due integer not null,
    ivl integer not null, factor integer not null, reps integer not null,
    lapses integer not null, left integer not null, odue integer not null,
    odid integer not null, flags integer not null, data text not null
);
CREATE TABLE revlog (
    id integer primary key, cid integer not null, usn integer not null,
    ease integer not null, ivl integer not null, lastIvl integer not null,
    factor integer not null, time integer not null, type integer not null
);
CREATE TABLE graves (usn integer not null, oid integer not null, type integer not null);
CREATE INDEX ix_notes_usn ON notes (usn);
CREATE INDEX ix_cards_usn ON cards (usn);
CREATE INDEX ix_revlog_usn ON revlog (usn);
CREATE INDEX ix_cards_nid ON cards (nid);
CREATE INDEX ix_cards_sched ON cards (did, queue, due);
CREATE INDEX ix_revlog_cid ON revlog (cid);
CREATE INDEX ix_notes_csum ON notes (csum);
"""

MODEL_CSS = """
.card {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 18px;
  line-height: 1.65;
  color: #1f2937;
  background: #ffffff;
  text-align: left;
  padding: 8px 4px;
}
.kiwi-stem { font-weight: 600; margin-bottom: 10px; }
.kiwi-options { margin: 8px 0 4px; }
.kiwi-option { margin: 3px 0; }
.kiwi-answer {
  margin-top: 14px;
  padding: 9px 12px;
  border-radius: 8px;
  background: #ecfdf5;
  color: #065f46;
}
.kiwi-explanation { margin-top: 10px; color: #475569; }
.kiwi-keypoints { margin-top: 10px; color: #475569; }
.kiwi-keypoints ul { margin: 4px 0 0; padding-left: 1.4em; }
.kiwi-source { margin-top: 12px; color: #94a3b8; font-size: 13px; }
hr#answer { border: 0; border-top: 1px solid #e2e8f0; margin: 14px 0; }
"""


@dataclass
class AnkiCard:
    """一张待导出卡片；``key`` 用作稳定的 guid 与整数 id。"""

    key: str
    deck: str
    front_html: str
    back_html: str
    tags: list[str]
    sort_field: str


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=False).replace("\n", "<br>")


def _plain(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _option_letter(index: int) -> str:
    return chr(ord("A") + index) if 0 <= index < 26 else str(index + 1)


def _as_index(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1


def _as_indexes(value: object) -> list[int]:
    if not isinstance(value, list):
        value = [value]
    return sorted({_as_index(item) for item in value if _as_index(item) >= 0})


def _clean_tag(value: str) -> str:
    """Anki 标签不能含空格；保留中文、字母数字和层级分隔符。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff:/-]+", "_", value.strip(), flags=re.UNICODE)
    return cleaned.strip("_")[:64]


def sanitize_deck_segment(value: str) -> str:
    """清理单个牌组层级内的文本，避免用户内容制造额外层级。"""
    segment = re.sub(r"[\x00-\x1f]+", " ", str(value or "")).strip()
    segment = segment.replace("::", "：").replace(":", "：").replace('"', "'")
    return segment[:80]


def sanitize_deck_name(value: str) -> str:
    """清理牌组名，同时保留调用方传入的 ``::`` 层级分隔符。"""
    segments = [
        sanitize_deck_segment(raw)
        for raw in str(value or "").split("::")
    ]
    return "::".join(segment for segment in segments if segment)[:160] or "未命名牌组"


def _render_front(question_json: Mapping, question_type: str) -> str:
    parts = [f'<div class="kiwi-stem">{_escape(question_json.get("question", ""))}</div>']
    options = [str(option) for option in question_json.get("options") or []]
    if options and question_type in {"single_choice", "multiple_choice"}:
        rendered = "".join(
            f'<div class="kiwi-option">{_option_letter(index)}. {_escape(option)}</div>'
            for index, option in enumerate(options)
        )
        parts.append(f'<div class="kiwi-options">{rendered}</div>')
    return "".join(parts)


def _render_answer(
    question_type: str,
    question_json: Mapping,
    answer_json: Mapping,
    cite_title: str,
) -> str:
    options = [str(option) for option in question_json.get("options") or []]
    explanation = question_json.get("explanation", "")
    parts: list[str] = []

    if question_type in {"single_choice", "true_false"}:
        index = _as_index(answer_json.get("correct_index", question_json.get("answer_index")))
        if 0 <= index < len(options):
            answer = f"{_option_letter(index)}. {_escape(options[index])}" if question_type == "single_choice" else _escape(options[index])
        else:
            answer = "（见解析）"
        parts.append(f'<div class="kiwi-answer"><b>答案</b>：{answer}</div>')
    elif question_type == "multiple_choice":
        indexes = _as_indexes(
            answer_json.get("correct_indexes") or question_json.get("answer_indexes")
        )
        labels = [
            f"{_option_letter(index)}. {_escape(options[index])}"
            for index in indexes
            if index < len(options)
        ]
        parts.append(
            f'<div class="kiwi-answer"><b>答案</b>：{"、".join(labels) or "（见解析）"}</div>'
        )
    elif question_type == "fill_blank":
        accepted = answer_json.get("accepted_answers") or []
        if isinstance(accepted, str):
            accepted = [accepted]
        answer = " / ".join(_escape(item) for item in accepted if str(item).strip())
        parts.append(f'<div class="kiwi-answer"><b>答案</b>：{answer or "（见解析）"}</div>')
    else:
        reference = answer_json.get("reference_answer") or ""
        parts.append(
            f'<div class="kiwi-answer"><b>参考答案</b>：{_escape(reference) or "（见解析）"}</div>'
        )
        key_points = answer_json.get("key_points") or []
        if key_points:
            items = "".join(f"<li>{_escape(point)}</li>" for point in key_points)
            parts.append(
                f'<div class="kiwi-keypoints"><b>关键要点</b><ul>{items}</ul></div>'
            )

    if explanation:
        parts.append(
            f'<div class="kiwi-explanation"><b>解析</b>：{_escape(explanation)}</div>'
        )
    if cite_title:
        parts.append(f'<div class="kiwi-source">来源：{_escape(cite_title)}</div>')
    return "".join(parts)


def question_to_card(
    *,
    question_id: object,
    question_type: str,
    question_json: Mapping | None,
    answer_json: Mapping | None,
    difficulty: str,
    deck: str,
    cite_title: str = "",
    topic_tag: str = "",
    extra_tags: list[str] | None = None,
) -> AnkiCard:
    question_json = question_json or {}
    answer_json = answer_json or {}
    question_type = question_type or "single_choice"
    front = _render_front(question_json, question_type)
    back = _render_answer(question_type, question_json, answer_json, cite_title)
    tags = ["kiwi", f"type::{question_type}", f"difficulty::{difficulty or 'basic'}"]
    if topic_tag:
        cleaned = _clean_tag(topic_tag)
        if cleaned:
            tags.append(f"topic::{cleaned}")
    for raw in extra_tags or []:
        cleaned = _clean_tag(str(raw))
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return AnkiCard(
        key=str(question_id),
        deck=sanitize_deck_name(deck),
        front_html=front,
        back_html=back,
        tags=tags,
        sort_field=_plain(question_json.get("question", ""))[:1000],
    )


def _int_id(prefix: str, key: str) -> int:
    """由题目 id 派生稳定的 63 位整数，重复导出不会产生随机差异。"""
    digest = hashlib.sha1(f"kiwi:{prefix}:{key}".encode()).hexdigest()
    return int(digest[:15], 16)


def _note_guid(key: str) -> str:
    return hashlib.sha1(f"kiwi:guid:{key}".encode()).hexdigest()[:20]


def _field_checksum(text: str) -> int:
    return int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)


def _model_json(deck_id: int) -> dict:
    fields = [
        {
            "name": name,
            "ord": index,
            "sticky": False,
            "rtl": False,
            "font": "Arial",
            "size": 20,
            "media": [],
        }
        for index, name in enumerate(("Front", "Back"))
    ]
    templates = [
        {
            "name": "Card 1",
            "ord": 0,
            "qfmt": "{{Front}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            "did": None,
            "bqfmt": "",
            "bafmt": "",
            "bfont": "",
            "bsize": 0,
        }
    ]
    return {
        str(MODEL_ID): {
            "id": MODEL_ID,
            "name": MODEL_NAME,
            "type": 0,
            "mod": int(time.time()),
            "usn": 0,
            "sortf": 0,
            "did": deck_id,
            "tmpls": templates,
            "flds": fields,
            "css": MODEL_CSS,
            "latexPre": (
                "\\documentclass[12pt]{article}\n"
                "\\special{papersize=3in,5in}\n"
                "\\usepackage[utf8]{inputenc}\n"
                "\\usepackage{amssymb,amsmath}\n"
                "\\pagestyle{empty}\n"
                "\\setlength{\\parindent}{0in}\n"
                "\\begin{document}\n"
            ),
            "latexPost": "\\end{document}",
            "latexsvg": False,
            "req": [[0, "any", [0]]],
        }
    }


def _deck_json(deck_id: int, name: str) -> dict:
    return {
        "id": deck_id,
        "name": name,
        "desc": "",
        "conf": 1,
        "usn": 0,
        "collapsed": False,
        "browserCollapsed": False,
        "newToday": [0, 0],
        "revToday": [0, 0],
        "lrnToday": [0, 0],
        "timeToday": [0, 0],
        "dyn": 0,
        "extendNew": 0,
        "extendRev": 0,
    }


def _dconf_json() -> dict:
    return {
        "1": {
            "id": 1,
            "name": "Default",
            "mod": 0,
            "usn": 0,
            "maxTaken": 60,
            "autoplay": True,
            "timer": 0,
            "replayq": True,
            "badges": True,
            "rev": {
                "perDay": 200,
                "ease4": 1.3,
                "fuzz": 0.05,
                "minSpace": 1,
                "ivlFct": 1,
                "maxIvl": 36500,
                "hardFactor": 1.2,
                "bury": True,
            },
            "new": {
                "perDay": 20,
                "delays": [1, 10],
                "ints": [1, 4, 0],
                "initialFactor": 2500,
                "order": 1,
                "bury": False,
                "separate": True,
            },
            "lapse": {
                "delays": [10],
                "mult": 0,
                "minInt": 1,
                "leechFails": 8,
                "leechAction": 0,
            },
            "dyn": False,
        }
    }


def _write_collection(
    path: Path, cards: list[AnkiCard], deck_root: str, created_at: datetime
) -> None:
    deck_names = [deck_root]
    for card in cards:
        if card.deck not in deck_names:
            deck_names.append(card.deck)
    deck_ids = {name: DECK_ID_BASE + index for index, name in enumerate(deck_names)}
    root_deck_id = deck_ids[deck_root]
    now_ms = int(created_at.timestamp() * 1000)
    now_s = int(created_at.timestamp())

    conf = {
        "activeDecks": [root_deck_id],
        "curDeck": root_deck_id,
        "newSpread": 0,
        "collapseTime": 1200,
        "timeLim": 0,
        "estTimes": True,
        "dueCounts": True,
        "curModel": MODEL_ID,
        "nextPos": len(cards) + 1,
        "sortType": "noteFld",
        "sortBackwards": False,
        "addToCur": True,
    }
    decks = {str(deck_ids[name]): _deck_json(deck_ids[name], name) for name in deck_names}
    models = _model_json(root_deck_id)
    dconf = _dconf_json()

    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO col VALUES (1, ?, ?, ?, 11, 0, 0, 0, ?, ?, ?, ?, '{}')",
            (
                now_s,
                now_ms,
                now_ms,
                json.dumps(conf, ensure_ascii=False),
                json.dumps(models, ensure_ascii=False),
                json.dumps(decks, ensure_ascii=False),
                json.dumps(dconf, ensure_ascii=False),
            ),
        )
        for order, card in enumerate(cards, start=1):
            note_id = _int_id("note", card.key)
            card_id = _int_id("card", card.key)
            tags = " " + " ".join(card.tags) + " "
            flds = f"{card.front_html}{FIELD_SEP}{card.back_html}"
            sort_field = card.sort_field or _plain(card.front_html)[:1000]
            connection.execute(
                "INSERT INTO notes VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, 0, '')",
                (
                    note_id,
                    _note_guid(card.key),
                    MODEL_ID,
                    now_s,
                    tags,
                    flds,
                    sort_field,
                    _field_checksum(sort_field),
                ),
            )
            connection.execute(
                "INSERT INTO cards VALUES (?, ?, ?, 0, ?, 0, 0, 0, ?, 0, 0, 0, 0, 0, 0, 0, 0, '')",
                (card_id, note_id, deck_ids[card.deck], now_s, order),
            )
        connection.commit()
    finally:
        connection.close()


def build_anki_package(
    cards: list[AnkiCard],
    deck_root: str,
    *,
    media: Mapping[str, bytes] | None = None,
    created_at: datetime | None = None,
) -> bytes:
    """把卡片打成 ``.apkg`` 字节流；``media`` 为文件名到内容的映射。"""
    if not cards:
        raise ValueError("没有可导出的题目")
    deck_root = sanitize_deck_name(deck_root)
    created_at = created_at or datetime.now(timezone.utc)
    media_names: dict[str, str] = {}
    media_items: list[bytes] = []
    for filename, content in (media or {}).items():
        media_names[str(len(media_items))] = filename
        media_items.append(content)

    buffer = BytesIO()
    with tempfile.TemporaryDirectory(prefix="kiwi-anki-") as tmp:
        collection_path = Path(tmp) / "collection.anki2"
        _write_collection(collection_path, cards, deck_root, created_at)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(collection_path, "collection.anki2")
            archive.writestr(
                "media", json.dumps(media_names, ensure_ascii=False)
            )
            for index, content in enumerate(media_items):
                archive.writestr(str(index), content)
    return buffer.getvalue()
