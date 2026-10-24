"""Anki `.apkg` 导出：卡片内容、牌组映射与集合格式。"""

from __future__ import annotations

import json
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from app.services.anki_export import (
    AnkiCard,
    build_anki_package,
    question_to_card,
)

FIXED_TIME = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _collection(tmp_path, payload: bytes) -> sqlite3.Connection:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert "collection.anki2" in archive.namelist()
        assert "media" in archive.namelist()
        (tmp_path / "collection.anki2").write_bytes(archive.read("collection.anki2"))
    return sqlite3.connect(tmp_path / "collection.anki2")


def test_question_to_card_renders_types_and_escapes_html():
    single = question_to_card(
        question_id=uuid.uuid4(),
        question_type="single_choice",
        question_json={
            "question": "缓存命中率 < 95% 时应该？",
            "options": ["扩容", "回源", "忽略"],
            "answer_index": 1,
            "explanation": "先回源保证正确性。",
        },
        answer_json={"correct_index": 1},
        difficulty="basic",
        deck="Kiwi::测试::单选",
        cite_title="缓存设计",
        topic_tag="cache/design",
    )
    assert "&lt; 95%" in single.front_html
    assert "B. 回源" in single.back_html
    assert "先回源保证正确性" in single.back_html
    assert "来源：缓存设计" in single.back_html
    assert "type::single_choice" in single.tags
    assert "topic::cache/design" in single.tags

    multiple = question_to_card(
        question_id=uuid.uuid4(),
        question_type="multiple_choice",
        question_json={
            "question": "以下哪些是缓存失效策略？",
            "options": ["TTL", "LRU", "TCP"],
            "answer_indexes": [0, 1],
        },
        answer_json={"correct_indexes": [0, 1]},
        difficulty="medium",
        deck="deck",
    )
    assert "A. TTL、B. LRU" in multiple.back_html

    true_false = question_to_card(
        question_id=uuid.uuid4(),
        question_type="true_false",
        question_json={"question": "缓存一定提升一致性。", "options": ["正确", "错误"]},
        answer_json={"correct_index": 1},
        difficulty="basic",
        deck="deck",
    )
    assert "错误" in true_false.back_html

    fill = question_to_card(
        question_id=uuid.uuid4(),
        question_type="fill_blank",
        question_json={"question": "并发控制的核心是____。"},
        answer_json={"accepted_answers": ["锁", "互斥量"]},
        difficulty="basic",
        deck="deck",
    )
    assert "锁 / 互斥量" in fill.back_html

    essay = question_to_card(
        question_id=uuid.uuid4(),
        question_type="essay",
        question_json={"question": "论述缓存一致性。", "explanation": "按要点评分。"},
        answer_json={
            "reference_answer": "先失效后更新。",
            "key_points": ["顺序", "补偿"],
        },
        difficulty="hard",
        deck="deck",
    )
    assert "参考答案" in essay.back_html
    assert "<li>顺序</li>" in essay.back_html
    assert "解析" in essay.back_html


def test_build_package_writes_schema_11_collection(tmp_path):
    first = question_to_card(
        question_id="q-1",
        question_type="single_choice",
        question_json={
            "question": "问题一",
            "options": ["甲", "乙"],
            "answer_index": 0,
        },
        answer_json={"correct_index": 0},
        difficulty="basic",
        deck="Kiwi::测试库::数据库",
        cite_title="页面一",
    )
    second = AnkiCard(
        key="q-2",
        deck="Kiwi::测试库::网络",
        front_html='<div class="kiwi-stem">问题二</div>',
        back_html='<div class="kiwi-answer">答案二</div>',
        tags=["kiwi", "type::true_false"],
        sort_field="问题二",
    )

    payload = build_anki_package(
        [first, second], "Kiwi::测试库", created_at=FIXED_TIME
    )
    connection = _collection(tmp_path, payload)
    try:
        row = connection.execute(
            "SELECT ver, conf, models, decks FROM col"
        ).fetchone()
        assert row[0] == 11
        conf = json.loads(row[1])
        decks = json.loads(row[3])
        deck_names = {deck["name"] for deck in decks.values()}
        assert deck_names == {
            "Kiwi::测试库",
            "Kiwi::测试库::数据库",
            "Kiwi::测试库::网络",
        }
        root_id = next(
            deck["id"] for deck in decks.values() if deck["name"] == "Kiwi::测试库"
        )
        assert conf["activeDecks"] == [root_id]
        model = next(iter(json.loads(row[2]).values()))
        assert model["name"] == "Kiwi 基础"
        assert [field["name"] for field in model["flds"]] == ["Front", "Back"]

        notes = connection.execute("SELECT tags, flds, sfld, csum FROM notes").fetchall()
        assert len(notes) == 2
        by_sort = {note[2]: note for note in notes}
        assert by_sort["问题一"][1].startswith('<div class="kiwi-stem">问题一</div>')
        assert "答案" in by_sort["问题一"][1]
        assert " type::single_choice " in by_sort["问题一"][0]
        assert by_sort["问题一"][3] > 0
        assert connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM revlog").fetchone()[0] == 0
        first_ids = connection.execute(
            "SELECT guid, id FROM notes ORDER BY sfld"
        ).fetchall()
        first_card_ids = connection.execute("SELECT id FROM cards ORDER BY id").fetchall()
    finally:
        connection.close()

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert json.loads(archive.read("media")) == {}

    # 同一批卡片重复导出时 guid / note id / card id 保持稳定，便于 Anki 去重。
    payload_again = build_anki_package(
        [first, second], "Kiwi::测试库", created_at=FIXED_TIME
    )
    connection = _collection(tmp_path, payload_again)
    try:
        assert (
            connection.execute("SELECT guid, id FROM notes ORDER BY sfld").fetchall()
            == first_ids
        )
        assert (
            connection.execute("SELECT id FROM cards ORDER BY id").fetchall()
            == first_card_ids
        )
    finally:
        connection.close()


async def test_export_endpoint_returns_package_and_deck_mapping(client, kb, db, tmp_path):
    from app.db.models import StudyQuestion

    question = StudyQuestion(
        kb_id=uuid.UUID(kb["id"]),
        fingerprint=uuid.uuid4().hex,
        question_type="single_choice",
        question_json={
            "question": "导出接口题目",
            "options": ["对", "错"],
            "answer_index": 0,
            "explanation": "导出解析",
        },
        answer_json={"correct_index": 0},
        difficulty="basic",
    )
    db.add(question)
    await db.commit()

    empty_kb = await client.post("/api/kbs", json={"name": f"anki-empty-{uuid.uuid4().hex[:8]}"})
    empty_id = empty_kb.json()["id"]
    try:
        missing = await client.get(f"/api/study/export/anki?kb_id={empty_id}")
        assert missing.status_code == 404

        response = await client.get(
            f"/api/study/export/anki?kb_id={kb['id']}&group_by=type"
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["x-kiwi-anki-count"] == "1"
        assert ".apkg" in response.headers["content-disposition"]

        connection = _collection(tmp_path, response.content)
        try:
            conf, decks = connection.execute("SELECT conf, decks FROM col").fetchone()
            deck_names = {item["name"] for item in json.loads(decks).values()}
            assert f"Kiwi::{kb['name']}::单选题" in deck_names
            assert json.loads(conf)["curDeck"]
            tags, flds = connection.execute("SELECT tags, flds FROM notes").fetchone()
            assert "type::single_choice" in tags
            assert "导出解析" in flds
        finally:
            connection.close()

        topic_response = await client.get(
            f"/api/study/export/anki?kb_id={kb['id']}&group_by=topic"
        )
        assert topic_response.status_code == 200
        connection = _collection(tmp_path, topic_response.content)
        try:
            decks = connection.execute("SELECT decks FROM col").fetchone()[0]
            assert f"Kiwi::{kb['name']}::未分类" in {
                item["name"] for item in json.loads(decks).values()
            }
        finally:
            connection.close()
    finally:
        await client.delete(f"/api/kbs/{empty_id}")
