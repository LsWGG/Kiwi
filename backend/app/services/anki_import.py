"""Anki `.apkg` 导入。

解析 Anki schema 11 集合（``collection.anki2`` / ``collection.anki21``），把
笔记转成 Kiwi 题库：识别单选、多选、判断、填空与简答题，保留牌组名、标签
和媒体文件。媒体复制到 ``/media/<kb_id>/anki-<token>/``，题目正文以纯文本
保存，媒体引用写入 ``question_json.media``，导出时可重新打包进牌组。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StudyQuestion

MAX_APKG_BYTES = 300 * 1024 * 1024
MAX_MEDIA_FILE_BYTES = 25 * 1024 * 1024
MAX_MEDIA_TOTAL_BYTES = 300 * 1024 * 1024
MAX_NOTES = 20_000
MAX_TAGS = 40

COLLECTION_NAMES = ("collection.anki21", "collection.anki2")
TRUE_FALSE_OPTIONS = {
    ("正确", "错误"),
    ("对", "错"),
    ("true", "false"),
    ("True", "False"),
}

_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::[^{}]*)?\}\}", re.DOTALL)
_OPTION_RE = re.compile(r"^([A-Za-z])[.、)．]\s*(.+)$")
_ANSWER_RE = re.compile(r"^(?:答案|正确答案|参考答案)\s*[:：]\s*(.*)$")
_EXPLANATION_RE = re.compile(r"^(?:解析|解释)\s*[:：]\s*(.*)$")
_SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")


class AnkiImportError(ValueError):
    """牌组无法解析时抛出，路由层转成 400。"""


@dataclass
class ParsedCard:
    deck: str
    question: str
    options: list[str]
    question_type: str
    question_json: dict[str, Any]
    answer_json: dict[str, Any]
    difficulty: str
    tags: list[str]
    media: list[str] = field(default_factory=list)


@dataclass
class ParsedDeck:
    cards: list[ParsedCard]
    media_names: dict[str, str]  # zip 内索引 -> 原始文件名
    skipped: int = 0


@dataclass
class AnkiImportResult:
    imported: int
    skipped: int
    media_files: int
    decks: list[str]


class _HtmlText(HTMLParser):
    """把 Anki 字段 HTML 转成带换行的纯文本，并收集图片 / 音频引用。"""

    _BLOCK_TAGS = {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "table",
        "tr",
        "blockquote",
        "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.media: list[tuple[str, str]] = []  # (src, kind)
        self._skip_depth = 0
        self._list_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "img":
            src = dict(attrs).get("src") or ""
            if src:
                self.media.append((src, "image"))
            self.parts.append("\n")
        elif tag in {"audio", "video"}:
            src = dict(attrs).get("src") or ""
            if src:
                self.media.append((src, tag))
            self.parts.append("\n")
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS or tag in {"li", "td", "th"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts).replace("\xa0", " ")
        lines = [line.strip() for line in raw.splitlines()]
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1] != "":
                cleaned.append("")
        return "\n".join(cleaned).strip()


def _html_text(value: str) -> tuple[str, list[tuple[str, str]]]:
    parser = _HtmlText()
    try:
        parser.feed(value or "")
        parser.close()
    except Exception:  # noqa: BLE001 - 损坏的 HTML 不应中断整个导入
        return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip(), parser.media
    return parser.text(), parser.media


def _clean_tags(raw: str) -> list[str]:
    tags = []
    for item in re.split(r"\s+", raw or ""):
        item = item.strip()
        if not item or item.lower() == "kiwi":
            continue
        tags.append(item[:64])
    return tags[:MAX_TAGS]


def _difficulty(tags: list[str]) -> str:
    for tag in tags:
        if tag.startswith("difficulty::"):
            value = tag.split("::", 1)[1]
            if value in {"basic", "medium", "hard"}:
                return value
    return "basic"


def _split_options(lines: list[str]) -> tuple[list[str], int]:
    """从题干尾部识别连续的 A/B/C… 选项，返回 (选项, 题干行数)。"""
    parsed: list[tuple[str, str]] = []
    index = len(lines)
    while index > 0:
        match = _OPTION_RE.match(lines[index - 1])
        if not match:
            break
        parsed.insert(0, (match.group(1).upper(), match.group(2).strip()))
        index -= 1
    letters = [letter for letter, _ in parsed]
    expected = [chr(ord("A") + i) for i in range(len(parsed))]
    if len(parsed) >= 2 and letters == expected:
        return [text for _, text in parsed], index
    return [], len(lines)


def _answer_indexes(value: str, options: list[str]) -> list[int]:
    letters = re.findall(r"(?<![A-Za-z])([A-Z])(?![A-Za-z])", value or "")
    indexes = sorted(
        {
            ord(letter) - ord("A")
            for letter in letters
            if 0 <= ord(letter) - ord("A") < len(options)
        }
    )
    if indexes:
        return indexes
    normalized = re.sub(r"\s+", "", value or "")
    for index, option in enumerate(options):
        if normalized and normalized == re.sub(r"\s+", "", option):
            return [index]
    return []


def _parse_back(
    back: str, options: list[str], question: str
) -> tuple[str, dict[str, Any], str, str]:
    """返回 (题型, answer_json, 解析, 原始答案文本)。"""
    lines = [line for line in back.splitlines() if line.strip()]
    answer_value = ""
    explanation_lines: list[str] = []
    for line in lines:
        answer_match = _ANSWER_RE.match(line)
        if answer_match and not answer_value:
            answer_value = answer_match.group(1).strip()
            continue
        explanation_match = _EXPLANATION_RE.match(line)
        if explanation_match:
            explanation_lines.append(explanation_match.group(1).strip())
            continue
        if line.startswith("来源："):
            continue
        explanation_lines.append(line)
    explanation = "\n".join(part for part in explanation_lines if part).strip()

    cloze_answers = [match.group(1).strip() for match in _CLOZE_RE.finditer(question)]
    if cloze_answers:
        return (
            "fill_blank",
            {"accepted_answers": [answer for answer in cloze_answers if answer]},
            explanation,
            " / ".join(cloze_answers),
        )

    if options:
        indexes = _answer_indexes(answer_value, options)
        if not indexes and answer_value:
            # 部分牌组直接把答案文本写在背面，没有 A/B 前缀。
            indexes = _answer_indexes(back, options)
        if not indexes and len(options) == 2:
            indexes = [0]
        if indexes:
            lowered = {option.strip().lower() for option in options}
            if len(options) == 2 and tuple(option.strip() for option in options) in TRUE_FALSE_OPTIONS:
                qtype = "true_false"
            elif len(options) == 2 and lowered in {("正确", "错误"), ("true", "false")}:
                qtype = "true_false"
            elif len(indexes) > 1:
                qtype = "multiple_choice"
            else:
                qtype = "single_choice"
            if qtype == "multiple_choice":
                return qtype, {"correct_indexes": indexes}, explanation, answer_value
            return qtype, {"correct_index": indexes[0]}, explanation, answer_value

    if "____" in question or "＿＿" in question or "（ ）" in question or "()" in question:
        accepted = [answer_value] if answer_value else []
        if not accepted and lines:
            accepted = [lines[0]]
        return (
            "fill_blank",
            {"accepted_answers": [item for item in accepted if item]},
            explanation,
            answer_value,
        )

    reference = answer_value or back.strip()
    return (
        "short_answer",
        {"reference_answer": reference, "key_points": []},
        explanation,
        answer_value,
    )


def _media_basename(src: str) -> str:
    raw = unquote(src.split("?", 1)[0].split("#", 1)[0]).replace("\\", "/")
    return raw.rsplit("/", 1)[-1]


def _media_lookup(media_names: dict[str, str]) -> dict[str, str]:
    """原始文件名 / 去扩展名文件名 -> zip 内索引。"""
    lookup: dict[str, str] = {}
    for index, name in media_names.items():
        lookup.setdefault(name.strip(), index)
        lookup.setdefault(Path(name).name, index)
    return lookup


def parse_apkg(payload: bytes) -> ParsedDeck:
    if not payload:
        raise AnkiImportError("牌组文件为空")
    if len(payload) > MAX_APKG_BYTES:
        raise AnkiImportError("牌组文件超过 300 MB 上限")
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise AnkiImportError("不是有效的 .apkg 牌组文件") from exc

    with archive:
        names = set(archive.namelist())
        collection = next((name for name in COLLECTION_NAMES if name in names), None)
        if collection is None:
            if "collection.anki21b" in names:
                raise AnkiImportError(
                    "该牌组使用新版 Anki 压缩格式，请在 Anki 导出时勾选"
                    "「支持旧版 Anki 版本」后重试"
                )
            raise AnkiImportError("牌组中缺少 collection.anki2 集合文件")
        if archive.getinfo(collection).file_size > MAX_APKG_BYTES:
            raise AnkiImportError("牌组集合解压后超过 300 MB 上限")
        collection_bytes = archive.read(collection)
        media_names: dict[str, str] = {}
        if "media" in names:
            try:
                raw_media = json.loads(archive.read("media").decode("utf-8") or "{}")
                if isinstance(raw_media, dict):
                    media_names = {
                        str(index): str(name)
                        for index, name in raw_media.items()
                        if str(name).strip()
                    }
            except (ValueError, UnicodeDecodeError):
                media_names = {}

        with tempfile.TemporaryDirectory(prefix="kiwi-anki-import-") as tmp:
            path = Path(tmp) / "collection.db"
            path.write_bytes(collection_bytes)
            cards = _read_collection(path, media_names)

    if not cards.cards and not cards.skipped:
        raise AnkiImportError("牌组中没有可导入的卡片")
    return cards


def _read_collection(path: Path, media_names: dict[str, str]) -> ParsedDeck:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise AnkiImportError("牌组集合无法打开，可能已损坏") from exc
    cards: list[ParsedCard] = []
    skipped = 0
    try:
        try:
            model_type_by_id: dict[str, int] = {}
            row = connection.execute("SELECT models FROM col LIMIT 1").fetchone()
            if row and row[0]:
                try:
                    models = json.loads(row[0])
                    if isinstance(models, dict):
                        model_type_by_id = {
                            str(model_id): int(model.get("type") or 0)
                            for model_id, model in models.items()
                            if isinstance(model, dict)
                        }
                except (ValueError, TypeError):
                    model_type_by_id = {}
            deck_names: dict[str, str] = {}
            row = connection.execute("SELECT decks FROM col LIMIT 1").fetchone()
            if row and row[0]:
                try:
                    decks = json.loads(row[0])
                    if isinstance(decks, dict):
                        deck_names = {
                            str(deck_id): str(deck.get("name") or "").strip()
                            for deck_id, deck in decks.items()
                            if isinstance(deck, dict)
                        }
                except (ValueError, TypeError):
                    deck_names = {}

            deck_by_note: dict[str, str] = {}
            for nid, did in connection.execute("SELECT nid, did FROM cards"):
                deck_by_note.setdefault(str(nid), deck_names.get(str(did), ""))

            for nid, flds, tags_raw, mid in connection.execute(
                "SELECT id, flds, tags, mid FROM notes"
            ):
                if len(cards) >= MAX_NOTES:
                    skipped += 1
                    continue
                card = _parse_note(
                    str(nid),
                    str(flds or ""),
                    str(tags_raw or ""),
                    str(mid or ""),
                    deck_by_note.get(str(nid), ""),
                    model_type_by_id.get(str(mid), 0),
                )
                if card is None:
                    skipped += 1
                else:
                    cards.append(card)
        except sqlite3.Error as exc:
            raise AnkiImportError("牌组集合格式无法识别，可能已损坏") from exc
    finally:
        connection.close()
    return ParsedDeck(cards=cards, media_names=media_names, skipped=skipped)


def _parse_note(
    note_id: str,
    flds: str,
    tags_raw: str,
    model_id: str,
    deck_raw: str,
    model_type: int,
) -> ParsedCard | None:
    fields = flds.split("\x1f")
    if not fields or not fields[0].strip():
        return None
    front_html = fields[0]
    back_html = fields[1] if len(fields) > 1 else ""
    if len(fields) > 2:
        back_html = "\n".join([back_html, *fields[2:]])

    front_text, front_media = _html_text(front_html)
    back_text, back_media = _html_text(back_html)
    if not front_text.strip():
        return None

    tags = _clean_tags(tags_raw)
    is_cloze = model_type == 1 or "{{c" in front_html
    question_text = front_text
    if is_cloze:
        question_text = _CLOZE_RE.sub("____", front_text)
    media = [src for src, _ in front_media + back_media if src]
    for sound in _SOUND_RE.findall(front_html + back_html):
        media.append(sound)

    lines = [line.strip() for line in question_text.splitlines() if line.strip()]
    options, question_line_count = ([], len(lines)) if is_cloze else _split_options(lines)
    question = "\n".join(lines[:question_line_count]).strip() or question_text.strip()
    if not question:
        return None

    question_type, answer_json, explanation, _ = _parse_back(back_text, options, front_text)
    question_json: dict[str, Any] = {
        "question": question,
        "options": options,
        "explanation": explanation,
        "anki_tags": tags,
        "deck": deck_raw,
        "anki_note_id": note_id,
    }
    return ParsedCard(
        deck=deck_raw or "未分类",
        question=question,
        options=options,
        question_type=question_type,
        question_json=question_json,
        answer_json=answer_json,
        difficulty=_difficulty(tags),
        tags=tags,
        media=media,
    )


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(value.replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f/:*?\"<>|]+", "_", name).strip("._ ")
    if not name:
        return fallback
    if len(name) > 120:
        stem, suffix = Path(name).stem[:90], Path(name).suffix[:20]
        name = f"{stem}{suffix}"
    return name


def _store_media(
    payload: bytes,
    media_names: dict[str, str],
    used: set[str],
    kb_id: uuid.UUID,
    media_root: Path,
) -> tuple[dict[str, dict[str, str]], int]:
    """把被题目引用的媒体写入 /media，返回引用名 -> 媒体描述。"""
    lookup = _media_lookup(media_names)
    if not used:
        return {}, 0
    token = uuid.uuid4().hex[:12]
    target_dir = media_root / str(kb_id) / f"anki-{token}"
    stored: dict[str, dict[str, str]] = {}
    entry_by_index: dict[str, dict[str, str]] = {}
    used_names: set[str] = set()
    written = 0
    total = 0
    image_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        for src in sorted(used):
            index = lookup.get(_media_basename(src)) or lookup.get(src.strip())
            if index is None or index not in media_names:
                continue
            if index in entry_by_index:
                stored[src] = entry_by_index[index]
                continue
            try:
                info = archive.getinfo(index)
            except KeyError:
                continue
            if info.file_size > MAX_MEDIA_FILE_BYTES:
                continue
            total += info.file_size
            if total > MAX_MEDIA_TOTAL_BYTES:
                break
            content = archive.read(index)
            original = media_names[index]
            name = _safe_filename(original, f"media-{index}")
            candidate = name
            suffix = Path(name).suffix
            counter = 2
            while candidate in used_names:
                candidate = f"{Path(name).stem}-{counter}{suffix}"
                counter += 1
            used_names.add(candidate)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / candidate).write_bytes(content)
            url = f"/media/{kb_id}/anki-{token}/{quote(candidate)}"
            entry = {
                "url": url,
                "name": original,
                "kind": "image" if Path(original).suffix.lower() in image_suffixes else "file",
            }
            entry_by_index[index] = entry
            stored[src] = entry
            written += 1
    return stored, written


def _fingerprint(kb_id: uuid.UUID, card: ParsedCard) -> str:
    raw = json.dumps(
        {
            "deck": card.deck,
            "question": card.question,
            "options": card.options,
            "answer": card.answer_json,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(f"anki:{kb_id}:{raw}".encode("utf-8")).hexdigest()


async def import_anki_package(
    session: AsyncSession,
    kb_id: uuid.UUID,
    payload: bytes,
    media_root: Path,
) -> AnkiImportResult:
    parsed = parse_apkg(payload)
    if not parsed.cards:
        raise AnkiImportError("牌组中没有可导入的卡片")

    used_media = {src for card in parsed.cards for src in card.media}
    media_by_src, media_count = _store_media(
        payload, parsed.media_names, used_media, kb_id, media_root
    )

    fingerprints: dict[str, ParsedCard] = {}
    for card in parsed.cards:
        fingerprints.setdefault(_fingerprint(kb_id, card), card)

    existing: set[str] = set()
    keys = list(fingerprints)
    for start in range(0, len(keys), 500):
        rows = await session.execute(
            select(StudyQuestion.fingerprint).where(
                StudyQuestion.kb_id == kb_id,
                StudyQuestion.fingerprint.in_(keys[start : start + 500]),
            )
        )
        existing.update(row[0] for row in rows)

    imported = 0
    decks: list[str] = []
    for fingerprint, card in fingerprints.items():
        if fingerprint in existing:
            continue
        question_json = dict(card.question_json)
        refs = [
            media_by_src[src]
            for src in dict.fromkeys(card.media)
            if src in media_by_src
        ]
        if refs:
            question_json["media"] = refs
        session.add(
            StudyQuestion(
                kb_id=kb_id,
                fingerprint=fingerprint,
                question_type=card.question_type,
                question_json=question_json,
                body_json={},
                answer_json=card.answer_json,
                difficulty=card.difficulty,
                confidence_level="unverified",
                cache_status="active",
            )
        )
        imported += 1
        if card.deck not in decks:
            decks.append(card.deck)
    await session.commit()
    return AnkiImportResult(
        imported=imported,
        skipped=len(parsed.cards) - imported + parsed.skipped,
        media_files=media_count,
        decks=decks,
    )
