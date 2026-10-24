"""Anki `.apkg` 导入：题型识别、去重、媒体与往返导出。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.models import StudyQuestion
from app.db.session import async_session_factory
from app.services.anki_export import AnkiCard, build_anki_package, question_to_card
from app.services.anki_import import parse_apkg

FIXED_TIME = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
PNG_BYTES = b"\x89PNG\r\n\x1a\nanki-media"


def _package() -> bytes:
    single = question_to_card(
        question_id="q-single",
        question_type="single_choice",
        question_json={
            "question": "缓存命中率低时应该？",
            "options": ["扩容", "回源", "忽略"],
            "answer_index": 1,
            "explanation": "先回源保证正确性。",
        },
        answer_json={"correct_index": 1},
        difficulty="medium",
        deck="Kiwi::测试::缓存",
    )
    single.front_html += '<div><img src="diagram.png"></div>'
    cloze = AnkiCard(
        key="q-cloze",
        deck="Kiwi::测试::填空",
        front_html="<div>HTTP 状态码 {{c1::404::未找到}} 表示资源不存在。</div>",
        back_html="<div>404 是客户端错误。</div>",
        tags=["type::fill_blank", "exam::网络"],
        sort_field="HTTP 状态码",
    )
    return build_anki_package(
        [single, cloze],
        "Kiwi::测试",
        media={"diagram.png": PNG_BYTES},
        created_at=FIXED_TIME,
    )


def _cleanup_media(kb_id: str) -> None:
    root = Path(settings.upload_dir) / "media" / kb_id
    if not root.is_dir():
        return
    for child in root.glob("anki-*"):
        if not child.is_dir():
            continue
        for item in child.iterdir():
            item.unlink()
        child.rmdir()
    try:
        root.rmdir()
    except OSError:
        pass


def test_parse_apkg_detects_types_tags_and_media():
    parsed = parse_apkg(_package())
    assert len(parsed.cards) == 2
    assert parsed.media_names == {"0": "diagram.png"}

    single = parsed.cards[0]
    assert single.question == "缓存命中率低时应该？"
    assert single.question_type == "single_choice"
    assert single.options == ["扩容", "回源", "忽略"]
    assert single.answer_json == {"correct_index": 1}
    assert single.deck == "Kiwi::测试::缓存"
    assert single.difficulty == "medium"
    assert "先回源保证正确性。" in single.question_json["explanation"]
    assert single.media == ["diagram.png"]

    cloze = parsed.cards[1]
    assert cloze.question_type == "fill_blank"
    assert "____" in cloze.question
    assert cloze.answer_json["accepted_answers"] == ["404"]
    assert "exam::网络" in cloze.tags


async def test_import_endpoint_dedupes_and_serves_media(client, kb):
    try:
        resp = await client.post(
            f"/api/study/import/anki?kb_id={kb['id']}",
            files={"file": ("demo.apkg", _package(), "application/octet-stream")},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["imported"] == 2
        assert data["skipped"] == 0
        assert data["media_files"] == 1
        assert "Kiwi::测试::缓存" in data["decks"]

        async with async_session_factory() as session:
            questions = (
                (
                    await session.execute(
                        select(StudyQuestion).where(StudyQuestion.kb_id == uuid.UUID(kb["id"]))
                    )
                )
                .scalars()
                .all()
            )
        assert len(questions) == 2
        media_urls = [
            ref["url"]
            for question in questions
            for ref in (question.question_json.get("media") or [])
        ]
        assert len(media_urls) == 1
        media = await client.get(media_urls[0])
        assert media.status_code == 200
        assert media.content == PNG_BYTES

        again = await client.post(
            f"/api/study/import/anki?kb_id={kb['id']}",
            files={"file": ("demo.apkg", _package(), "application/octet-stream")},
        )
        assert again.status_code == 200, again.text
        assert again.json()["imported"] == 0
        assert again.json()["skipped"] == 2

        exported = await client.get(
            f"/api/study/export/anki?kb_id={kb['id']}&group_by=topic"
        )
        assert exported.status_code == 200, exported.text
        roundtrip = parse_apkg(exported.content)
        assert len(roundtrip.cards) == 2
        assert any(card.media for card in roundtrip.cards)
        assert any(
            "exam::网络" in card.tags for card in roundtrip.cards
        )
    finally:
        _cleanup_media(kb["id"])


async def test_import_rejects_invalid_archive(client, kb):
    resp = await client.post(
        f"/api/study/import/anki?kb_id={kb['id']}",
        files={"file": ("bad.apkg", b"not a zip", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "牌组" in resp.json()["detail"]
