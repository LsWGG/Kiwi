"""知识库全量导入导出（Kiwi 专用 ``.kiwizip`` 格式）。

导出包结构::

    manifest.json   # 格式标识、版本、知识库信息、文件清单
    data.json       # 全部业务表行（UUID 以字符串保存）
    files/...       # 原始素材与附件

导入始终创建一个新的知识库：所有主键与外键重新映射，笔记正文 / 属性中
的 ``kiwi://note/<id>``、``kiwi://wiki/<id>`` 与媒体地址同步改写，因此
可以安全地重复导入，不会与已有数据冲突。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, datetime, timezone
from hashlib import sha1
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from sqlalchemy import Date, DateTime, Uuid, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    CollectionRow,
    ExamTemplate,
    KnowledgeBase,
    LearningAnnotation,
    LearningTopic,
    LLMConfig,
    MockExam,
    MockExamItem,
    Note,
    NoteAttachment,
    NoteCollection,
    NoteFolder,
    NoteLink,
    NoteRevision,
    NoteTag,
    NoteTagLink,
    NoteTemplate,
    Source,
    StudyAttempt,
    StudyPlan,
    StudyProfile,
    StudyQuestion,
    StudyReview,
    StudySession,
    TodoMirror,
    WebResearchLog,
    WikiLink,
    WikiLintReport,
    WikiPage,
)
from app.db.session import async_session_factory

logger = logging.getLogger("kiwi.transfer")

FORMAT = "kiwi-kb"
VERSION = 1
MAX_PACKAGE_BYTES = 500 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1500 * 1024 * 1024
MAX_DATA_BYTES = 300 * 1024 * 1024
MAX_ROWS = 200_000
IMPORT_EXT = {".md", ".markdown", ".txt", ".text", ".pdf", ".docx", ".doc"}


class TransferError(Exception):
    pass


# 导出 / 导入顺序：被引用的表在前，引用方在后。
TABLE_ORDER: list[tuple[str, Any]] = [
    ("knowledge_bases", KnowledgeBase),
    ("exam_templates", ExamTemplate),
    ("wiki_pages", WikiPage),
    ("sources", Source),
    ("note_folders", NoteFolder),
    ("notes", Note),
    ("note_tags", NoteTag),
    ("note_tag_links", NoteTagLink),
    ("note_links", NoteLink),
    ("note_collections", NoteCollection),
    ("collection_rows", CollectionRow),
    ("note_revisions", NoteRevision),
    ("note_attachments", NoteAttachment),
    ("note_templates", NoteTemplate),
    ("study_profiles", StudyProfile),
    ("study_questions", StudyQuestion),
    ("study_sessions", StudySession),
    ("learning_topics", LearningTopic),
    ("study_reviews", StudyReview),
    ("mock_exams", MockExam),
    ("mock_exam_items", MockExamItem),
    ("study_attempts", StudyAttempt),
    ("study_plans", StudyPlan),
    ("web_research_logs", WebResearchLog),
    ("learning_annotations", LearningAnnotation),
    ("wiki_lint_reports", WikiLintReport),
    ("wiki_links", WikiLink),
]

# ---------------------------------------------------------------- helpers

def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w一-鿿-]+", "-", (name or "").lower()).strip("-")[:100]
    return slug or "kb"


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _row_dict(obj: Any) -> dict:
    mapper = inspect(type(obj))
    return {col.key: getattr(obj, col.key) for col in mapper.columns}


def _export_rows_filter(model: Any, kb_id: uuid.UUID):
    """返回 select(model) 的知识库范围条件。"""
    if model is KnowledgeBase:
        return select(model).where(model.id == kb_id)
    if hasattr(model, "kb_id"):
        return select(model).where(model.kb_id == kb_id)
    if model is NoteTagLink:
        return (
            select(NoteTagLink)
            .join(Note, Note.id == NoteTagLink.note_id)
            .where(Note.kb_id == kb_id)
        )
    if model is NoteLink:
        return (
            select(NoteLink)
            .join(Note, Note.id == NoteLink.from_note_id)
            .where(Note.kb_id == kb_id)
        )
    if model is WikiLink:
        return (
            select(WikiLink)
            .join(WikiPage, WikiPage.id == WikiLink.from_page_id)
            .where(WikiPage.kb_id == kb_id)
        )
    if model is MockExamItem:
        return (
            select(MockExamItem)
            .join(MockExam, MockExam.id == MockExamItem.mock_exam_id)
            .where(MockExam.kb_id == kb_id)
        )
    raise TransferError(f"无法确定表 {model.__tablename__} 的知识库范围")


async def _collect_rows(session: AsyncSession, kb_id: uuid.UUID) -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for name, model in TABLE_ORDER:
        rows = (
            (await session.execute(_export_rows_filter(model, kb_id))).scalars().all()
        )
        data[name] = [json.loads(json.dumps(_row_dict(row), default=_json_default)) for row in rows]
    return data


def _media_root() -> Path:
    return settings.upload_dir / "media"


def _safe_ext(path: str) -> str:
    ext = re.sub(r"[^a-z0-9.]", "", Path(path).suffix.lower())[:16]
    return ext or ".bin"


async def build_export(session: AsyncSession, kb_id: uuid.UUID) -> tuple[str, str]:
    """生成导出包，返回 (临时文件路径, 下载文件名)。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.deleted_at is not None:
        raise TransferError("知识库不存在")

    data = await _collect_rows(session, kb_id)
    files: list[dict] = []

    # 写入临时文件，避免大知识库全部驻留内存
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".kiwizip")
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for source in data.get("sources", []):
                raw = source.get("raw_path") or ""
                path = Path(raw)
                if not path.exists() or not path.is_file():
                    continue
                ext = _safe_ext(path.name)
                archive_path = f"files/sources/{source['id']}{ext}"
                zf.write(path, archive_path)
                files.append(
                    {
                        "kind": "source",
                        "old_id": source["id"],
                        "archive_path": archive_path,
                        "filename": path.name,
                        "ext": ext,
                    }
                )
            for attachment in data.get("note_attachments", []):
                storage_path = attachment.get("storage_path") or ""
                if not storage_path:
                    continue
                path = _media_root() / storage_path
                if not path.exists() or not path.is_file():
                    continue
                ext = _safe_ext(path.name)
                archive_path = f"files/media/{attachment['id']}{ext}"
                zf.write(path, archive_path)
                files.append(
                    {
                        "kind": "attachment",
                        "old_id": attachment["id"],
                        "old_storage_path": storage_path,
                        "archive_path": archive_path,
                        "filename": attachment.get("filename") or path.name,
                        "content_type": attachment.get("content_type") or "",
                        "ext": ext,
                    }
                )

            manifest = {
                "format": FORMAT,
                "version": VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "app": "Kiwi",
                "kb": {
                    "id": str(kb.id),
                    "name": kb.name,
                    "slug": kb.slug,
                    "description": kb.description,
                    "embedding_model": kb.embedding_model,
                    "learning_enabled": bool(kb.learning_enabled),
                },
                "counts": {name: len(rows) for name, rows in data.items() if rows},
                "files": files,
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            zf.writestr(
                "data.json",
                json.dumps(data, ensure_ascii=False),
            )
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise

    filename = f"{_slugify(kb.name)}-{datetime.now().strftime('%Y%m%d')}.kiwizip"
    return tmp.name, filename


# ---------------------------------------------------------------- import

def _validate_zip(zf: zipfile.ZipFile) -> None:
    infos = zf.infolist()
    if len(infos) > 20_000:
        raise TransferError("导出包条目过多")
    total = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise TransferError("导出包包含非法路径")
        if info.flag_bits & 0x1:
            raise TransferError("导出包包含加密条目")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise TransferError("导出包解压后体积超过上限")
    if "manifest.json" not in zf.namelist() or "data.json" not in zf.namelist():
        raise TransferError("不是有效的 Kiwi 知识库导出包")


def _read_json(zf: zipfile.ZipFile, name: str) -> Any:
    info = zf.getinfo(name)
    if info.file_size > MAX_DATA_BYTES:
        raise TransferError(f"{name} 超过大小上限")
    try:
        with zf.open(info) as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransferError(f"{name} 格式损坏") from exc


def _replace_json(value: Any, replace: dict[str, str]) -> Any:
    if isinstance(value, str):
        for old, new in replace.items():
            if old in value:
                value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_replace_json(item, replace) for item in value]
    if isinstance(value, dict):
        return {
            _replace_json(key, replace): _replace_json(item, replace)
            for key, item in value.items()
        }
    return value


def _convert_value(column, value: Any, replace: dict[str, str]):
    if value is None:
        return None
    value = _replace_json(value, replace)
    col_type = column.type
    if isinstance(col_type, Uuid):
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError):
            return None
    if isinstance(col_type, DateTime):
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if isinstance(col_type, Date):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return value


def _foreign_key_columns(model) -> set[str]:
    return {
        col.key
        for col in inspect(model).columns
        if any(True for _ in col.foreign_keys)
    }


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = _slugify(name)
    slug = f"{base}-import"
    while (
        await session.execute(select(KnowledgeBase.id).where(KnowledgeBase.slug == slug))
    ).scalar_one_or_none() is not None:
        slug = f"{base}-import-{uuid.uuid4().hex[:4]}"
    return slug


async def import_package(session: AsyncSession, package_path: Path) -> tuple[KnowledgeBase, dict]:
    """导入 .kiwizip；返回 (新知识库, 统计)。"""
    if package_path.stat().st_size > MAX_PACKAGE_BYTES:
        raise TransferError("导出包超过 500MB 上限")
    try:
        zf = zipfile.ZipFile(package_path)
    except zipfile.BadZipFile as exc:
        raise TransferError("文件不是有效的 ZIP / .kiwizip 包") from exc

    created_files: list[Path] = []
    try:
        with zf:
            _validate_zip(zf)
            manifest = _read_json(zf, "manifest.json")
            if manifest.get("format") != FORMAT:
                raise TransferError("不是 Kiwi 知识库导出包")
            if int(manifest.get("version") or 0) > VERSION:
                raise TransferError("导出包版本高于当前系统，请先升级 Kiwi")
            data = _read_json(zf, "data.json")
            if not isinstance(data, dict):
                raise TransferError("data.json 结构无效")
            total_rows = sum(
                len(rows) for rows in data.values() if isinstance(rows, list)
            )
            if total_rows > MAX_ROWS:
                raise TransferError("导出包含记录过多")

            kb_rows = data.get("knowledge_bases") or []
            if len(kb_rows) != 1:
                raise TransferError("导出包必须且只能包含一个知识库")
            old_kb = kb_rows[0]
            old_kb_id = str(old_kb.get("id"))
            new_kb_id = uuid.uuid4()

            # 1) 为所有带主键的行生成新 UUID
            id_map: dict[str, str] = {old_kb_id: str(new_kb_id)}
            for name, _model in TABLE_ORDER:
                if _model is KnowledgeBase:
                    continue
                for row in data.get(name) or []:
                    old_id = row.get("id")
                    if old_id:
                        id_map[str(old_id)] = str(uuid.uuid4())

            # 2) 文件落盘（先写文件，数据库失败时清理）
            file_overrides: dict[tuple[str, str], dict] = {}
            replace = dict(id_map)
            for entry in manifest.get("files") or []:
                kind = entry.get("kind")
                old_id = str(entry.get("old_id"))
                new_id = id_map.get(old_id)
                archive_path = entry.get("archive_path") or ""
                if not new_id or not archive_path:
                    continue
                info = zf.getinfo(archive_path)
                if info.file_size > MAX_UNCOMPRESSED_BYTES:
                    raise TransferError("导出包内单个文件过大")
                ext = entry.get("ext") or _safe_ext(archive_path)
                if kind == "source":
                    target = settings.upload_dir / str(new_kb_id) / f"{new_id}{ext}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    created_files.append(target)
                    file_overrides[("source", new_id)] = {"raw_path": str(target)}
                elif kind == "attachment":
                    storage_path = f"{new_kb_id}/{new_id}{ext}"
                    target = _media_root() / storage_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    created_files.append(target)
                    old_storage = str(entry.get("old_storage_path") or "")
                    if old_storage:
                        replace[old_storage] = storage_path
                    file_overrides[("attachment", new_id)] = {
                        "storage_path": storage_path
                    }
                    # 正文里的 /media/<path> 引用同步改写
                    if old_storage:
                        replace[f"/media/{old_storage}"] = f"/media/{storage_path}"

            # 3) 创建新知识库
            name = str(manifest.get("kb", {}).get("name") or old_kb.get("name") or "导入知识库")
            # 知识库名称允许重复（slug 才是唯一键），这里只判断是否需要改名；
            # 不能用 scalar_one_or_none，否则库中已有多个同名知识库时会直接 500。
            duplicate = (
                await session.execute(
                    select(KnowledgeBase.id)
                    .where(KnowledgeBase.name == name)
                    .limit(1)
                )
            ).scalars().first()
            if duplicate is not None:
                name = f"{name}（导入）"
            max_sort = (
                (await session.execute(select(KnowledgeBase.sort_order)))
                .scalars()
                .all()
            )
            kb = KnowledgeBase(
                id=new_kb_id,
                name=name[:200],
                slug=await _unique_slug(session, name),
                description=str(old_kb.get("description") or ""),
                embedding_model=str(
                    old_kb.get("embedding_model") or settings.embed_model
                )[:200],
                learning_enabled=bool(old_kb.get("learning_enabled", True)),
                pinned=False,
                is_builtin=False,
                builtin_key=None,
                deleted_at=None,
                sort_order=(max(max_sort) + 1) if max_sort else 0,
            )
            old_llm_id = old_kb.get("llm_config_id")
            if old_llm_id:
                try:
                    if await session.get(LLMConfig, uuid.UUID(str(old_llm_id))) is not None:
                        kb.llm_config_id = uuid.UUID(str(old_llm_id))
                except (ValueError, TypeError):
                    pass
            session.add(kb)
            await session.flush()

            # 4) 按依赖顺序导入各表
            stats: dict[str, int] = {}
            self_ref: list[tuple[Any, dict[str, Any]]] = []

            for name, model in TABLE_ORDER:
                if model is KnowledgeBase:
                    # 新知识库已在上面单独创建，跳过整行复制。
                    continue
                rows = data.get(name) or []
                if not isinstance(rows, list):
                    continue
                columns = {col.key: col for col in inspect(model).columns}
                fk_columns = _foreign_key_columns(model)
                count = 0
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    values: dict[str, Any] = {}
                    skip = False
                    for key, column in columns.items():
                        if key not in raw:
                            continue
                        # kb_id 统一指向新建知识库；知识库主键不在 id_map 中。
                        if key == "kb_id":
                            values[key] = new_kb_id
                            continue
                        # 外键必须用包内原始 id 查映射表。不能先走 _convert_value，
                        # 否则 _replace_json 会把 id 改写成新 id，导致查不到映射。
                        if key in fk_columns:
                            raw_fk = raw.get(key)
                            if raw_fk is None:
                                values[key] = None
                                continue
                            mapped = id_map.get(str(raw_fk))
                            if mapped is None:
                                if column.nullable:
                                    values[key] = None
                                else:
                                    skip = True
                                    break
                            else:
                                values[key] = uuid.UUID(mapped)
                            continue
                        values[key] = _convert_value(column, raw.get(key), replace)
                    if skip:
                        continue
                    if model is NoteFolder or model is NoteTag:
                        # 自引用稍后统一处理，避免父节点尚未插入
                        parent_id = values.pop("parent_id", None)
                        obj = model(**values)
                        session.add(obj)
                        self_ref.append((obj, {"parent_id": parent_id}))
                    else:
                        obj = model(**values)
                        session.add(obj)
                    if name == "study_questions":
                        old_fp = str(raw.get("fingerprint") or "")
                        if old_fp:
                            obj.fingerprint = sha1(
                                f"{obj.id}:{old_fp}".encode("utf-8")
                            ).hexdigest()
                    count += 1
                if name in ("note_folders", "note_tags") and self_ref:
                    await session.flush()
                    for obj, extra in self_ref:
                        parent = extra.get("parent_id")
                        if parent is not None:
                            obj.parent_id = parent
                    self_ref.clear()
                # 文件路径覆盖
                for obj in session.new:
                    if not isinstance(obj, (Source, NoteAttachment)):
                        continue
                    kind = "source" if isinstance(obj, Source) else "attachment"
                    override = file_overrides.get((kind, str(obj.id)))
                    if override:
                        for key, value in override.items():
                            setattr(obj, key, value)
                await session.flush()
                stats[name] = count

            # 5) 同步强制刷新收件箱（不导入派生镜像）
            await session.commit()
    except Exception:
        try:
            if not session.is_active:
                await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        for path in created_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        zf.close()

    stats["files"] = len(created_files)
    # 后台重建向量索引，不阻塞导入响应。
    asyncio.create_task(_reindex_imported(new_kb_id), name=f"kb-import-index:{new_kb_id}")
    return kb, stats


async def _reindex_imported(kb_id: uuid.UUID) -> None:
    try:
        from app.services import qdrant_store
        from app.services.embedder import embed_texts_async
        from app.services.note_indexer import ensure_notes_indexed

        await ensure_notes_indexed([kb_id], force=True)
        async with async_session_factory() as db:
            kb = await db.get(KnowledgeBase, kb_id)
            if kb is None:
                return
            pages = list(
                (
                    await db.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))
                )
                .scalars()
                .all()
            )
            if not pages:
                return
            texts = [f"{page.title}\n{page.body_md[:2000]}" for page in pages]
            vectors = await embed_texts_async(texts, kb.embedding_model)
            for page in pages:
                await asyncio.to_thread(
                    qdrant_store.delete_wiki_page, kb_id, page.id, kb.embedding_model
                )
            points = [
                {
                    "vector": vector,
                    "payload": {
                        "page_id": str(page.id),
                        "title": page.title,
                        "slug": page.slug,
                        "body_head": page.body_md[:500],
                        "human_edited": page.human_edited,
                    },
                }
                for page, vector in zip(pages, vectors)
            ]
            await asyncio.to_thread(
                qdrant_store.upsert_wiki_pages, kb_id, points, kb.embedding_model
            )
    except Exception:  # noqa: BLE001
        logger.exception("导入知识库 %s 的向量重建失败", kb_id)
