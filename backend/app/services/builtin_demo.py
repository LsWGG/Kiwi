"""系统内置演示知识库：随应用启动幂等落库，支持隐藏与还原。

演示数据是一份 Kiwi 上手指南：以「三周搭建团队知识库」为主线，覆盖笔记 /
画布 / 数据表 / Notebook / 导入 / 外链 / Wiki / 图谱 / 学习模式 / 仿真考试
等全部功能。内容围绕系统自身的能力与操作示例展开，读完后可以直接上手。

设计要点：
- 固定 UUID + ``builtin_key='demo'``；检测到旧版业务演示库时先清理再重建；
- 全部写入在同一事务内完成，失败回滚，避免留下半成品；
- 内置库删除为软删除（``deleted_at``），不清理向量与素材，随时可还原；
- 向量索引在后台补齐，失败只记日志，不影响应用启动。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    CollectionRow,
    KnowledgeBase,
    LearningAnnotation,
    LearningTopic,
    MockExam,
    MockExamItem,
    Note,
    NoteCollection,
    NoteFolder,
    NoteLink,
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
    WikiLink,
    WikiPage,
)
from app.db.session import async_session_factory

logger = logging.getLogger("kiwi.builtin_demo")

BUILTIN_KEY = "demo"
BUILTIN_KB_ID = uuid.UUID("6f3a1c2e-8b4d-4e9a-9c7f-2a5d8e1b4c60")
# 旧版业务演示库（云杉华东仓 AMR）：升级时清理并按新内容重建
LEGACY_BUILTIN_KB_ID = uuid.UUID("b338109b-0d45-401d-b026-4d9500bb9ba0")
BUILTIN_NAME = "Kiwi 上手指南 · 功能演示知识库"
BUILTIN_SLUG = "kiwi-getting-started"
ASSETS_DIR = Path(__file__).resolve().parent / "builtin_demo_assets"
SEED_FILE = ASSETS_DIR / "demo_seed.json"

# 插入顺序按外键依赖排列；同一组内一次 flush。
_SEED_GROUPS: list[tuple[str, Any]] = [
    ("note_folders", NoteFolder),
    ("note_tags", NoteTag),
    ("note_templates", NoteTemplate),
    ("sources", Source),
    ("notes", Note),
    ("note_links", NoteLink),
    ("note_collections", NoteCollection),
    ("collection_rows", CollectionRow),
    ("wiki_pages", WikiPage),
    ("wiki_links", WikiLink),
    ("note_tag_links", NoteTagLink),
    ("study_profiles", StudyProfile),
    ("learning_topics", LearningTopic),
    ("study_sessions", StudySession),
    ("study_questions", StudyQuestion),
    ("study_reviews", StudyReview),
    ("mock_exams", MockExam),
    ("study_attempts", StudyAttempt),
    ("study_plans", StudyPlan),
    ("mock_exam_items", MockExamItem),
    ("learning_annotations", LearningAnnotation),
]


def _coerce_value(column: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, Uuid) and isinstance(value, str):
        return uuid.UUID(value)
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _clean_row(model: Any, row: dict[str, Any]) -> dict[str, Any]:
    """只保留模型真实列，并做 UUID / 时间类型转换。"""
    columns = {column.key: column for column in model.__table__.columns}
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        column = columns.get(key)
        if column is None:
            continue
        cleaned[key] = _coerce_value(column, value)
    return cleaned


def _order_tree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把自引用 parent_id 的行排成父先子后，满足即时外键校验。"""
    by_id = {row["id"]: row for row in rows}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(row: dict[str, Any]) -> None:
        if row["id"] in seen:
            return
        parent_id = row.get("parent_id")
        if parent_id and parent_id in by_id and parent_id not in seen:
            visit(by_id[parent_id])
        seen.add(row["id"])
        ordered.append(row)

    for row in rows:
        visit(row)
    return ordered


def _copy_assets() -> None:
    """把随包素材复制到运行时上传目录（幂等，固定文件覆盖写）。"""
    upload_root = Path(settings.upload_dir)
    for source in ASSETS_DIR.glob("uploads/**/*"):
        if not source.is_file():
            continue
        relative = source.relative_to(ASSETS_DIR / "uploads")
        target = upload_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    for source in ASSETS_DIR.glob("media/**/*"):
        if not source.is_file():
            continue
        relative = source.relative_to(ASSETS_DIR / "media")
        target = upload_root / "media" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())


async def _unique_slug(session: AsyncSession) -> str:
    taken = (
        await session.execute(select(KnowledgeBase.id).where(KnowledgeBase.slug == BUILTIN_SLUG))
    ).scalar_one_or_none()
    if taken is None:
        return BUILTIN_SLUG
    return f"{BUILTIN_SLUG}-demo"


async def _insert_seed(session: AsyncSession, kb: KnowledgeBase) -> None:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))

    # 考试模板是全局内置数据，需先确保存在，再重映射演示考试的外键。
    from app.db.models import ExamTemplate
    from app.services.study_engine import ensure_builtin_templates

    await ensure_builtin_templates(session)
    generic = (
        (
            await session.execute(
                select(ExamTemplate).where(
                    ExamTemplate.code == "generic_exam", ExamTemplate.is_builtin.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    for exam in data.get("mock_exams") or []:
        exam["exam_template_id"] = str(generic.id) if generic is not None else None

    session.add(kb)
    await session.flush()

    for key, model in _SEED_GROUPS:
        rows = data.get(key) or []
        if key in {"note_folders", "note_tags"}:
            rows = _order_tree(rows)
        objects = [model(**_clean_row(model, row)) for row in rows]
        if objects:
            session.add_all(objects)
            await session.flush()

    # 演示库不应绑定开发机上的 LLM 配置，统一回落全局默认。
    kb.llm_config_id = None


async def _purge_legacy_builtin(session: AsyncSession, kb: KnowledgeBase) -> datetime | None:
    """清理旧版演示库：先清向量与内核，再让数据库级联删除。"""
    hidden_at = kb.deleted_at
    kb_id = kb.id
    try:
        from app.services import qdrant_store

        qdrant_store.purge_kb(kb_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("旧版演示库向量清理失败（不影响重建）：%s", exc)
    try:
        from app.services.notebook_kernel import kernel_manager

        kernel_manager.purge_kb(str(kb_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("旧版演示库内核清理失败（不影响重建）：%s", exc)
    await session.delete(kb)
    await session.flush()
    logger.info("已清理旧版演示库：%s", kb_id)
    return hidden_at


async def ensure_builtin_demo(session: AsyncSession) -> tuple[KnowledgeBase | None, bool]:
    """确保内置演示库存在并标记为 builtin。

    返回 ``(kb, just_seeded)``。已隐藏（deleted_at 非空）时不会自动还原。
    检测到旧版业务演示库时，会先清理并按当前随包内容重建。
    """
    if not SEED_FILE.exists():
        logger.warning("内置演示数据缺失：%s", SEED_FILE)
        return None, False

    kb = (
        await session.execute(
            select(KnowledgeBase).where(KnowledgeBase.builtin_key == BUILTIN_KEY)
        )
    ).scalars().first()

    legacy_hidden_at: datetime | None = None

    # 旧版（AMR 业务演示）使用另一个固定 ID；内置还原始终应展示当前随包内容。
    if kb is not None and kb.id != BUILTIN_KB_ID:
        legacy_hidden_at = await _purge_legacy_builtin(session, kb)
        kb = None

    # 兼容 builtin_key 缺失但固定 ID 命中的历史数据；只处理明确标记为 builtin 的库。
    legacy = await session.get(KnowledgeBase, LEGACY_BUILTIN_KB_ID)
    if legacy is not None and legacy.is_builtin and legacy.id != BUILTIN_KB_ID:
        hidden = await _purge_legacy_builtin(session, legacy)
        legacy_hidden_at = legacy_hidden_at or hidden

    if kb is not None:
        changed = False
        if not kb.is_builtin:
            kb.is_builtin = True
            changed = True
        if kb.builtin_key != BUILTIN_KEY:
            owner = (
                await session.execute(
                    select(KnowledgeBase.id).where(
                        KnowledgeBase.builtin_key == BUILTIN_KEY,
                        KnowledgeBase.id != kb.id,
                    )
                )
            ).scalar_one_or_none()
            if owner is None:
                kb.builtin_key = BUILTIN_KEY
                changed = True
        if changed:
            await session.commit()
        _copy_assets()
        return kb, False

    # 全新安装 / 旧库升级：创建并一次性写入全部演示数据。
    _copy_assets()
    kb = KnowledgeBase(
        id=BUILTIN_KB_ID,
        name=BUILTIN_NAME,
        slug=await _unique_slug(session),
        description=(
            "系统内置的 Kiwi 上手指南：以「三周搭建团队知识库」为示例主线，"
            "演示笔记、画布、数据表、Notebook、导入、外链、Wiki、知识图谱、"
            "学习模式与仿真考试。内容即操作说明，可自由修改；删除后可在知识库页还原。"
        ),
        pinned=True,
        learning_enabled=True,
        is_builtin=True,
        builtin_key=BUILTIN_KEY,
        deleted_at=legacy_hidden_at,
    )
    try:
        await _insert_seed(session, kb)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("内置演示库写入失败，已回滚")
        return None, False

    logger.info("内置演示库已创建：%s (%s)", kb.name, kb.id)
    return kb, True


async def get_builtin_status(session: AsyncSession) -> dict[str, Any]:
    kb = (
        await session.execute(
            select(KnowledgeBase).where(KnowledgeBase.builtin_key == BUILTIN_KEY)
        )
    ).scalars().first()
    if kb is None:
        return {
            "key": BUILTIN_KEY,
            "name": BUILTIN_NAME,
            "exists": False,
            "deleted": False,
            "kb_id": None,
        }
    return {
        "key": BUILTIN_KEY,
        "name": kb.name or BUILTIN_NAME,
        "exists": True,
        "deleted": kb.deleted_at is not None,
        "kb_id": kb.id,
    }


async def restore_builtin(session: AsyncSession) -> KnowledgeBase | None:
    kb = (
        await session.execute(
            select(KnowledgeBase).where(KnowledgeBase.builtin_key == BUILTIN_KEY)
        )
    ).scalars().first()
    if kb is None:
        kb, _ = await ensure_builtin_demo(session)
        if kb is None:
            return None
    if kb.deleted_at is not None:
        kb.deleted_at = None
    kb.is_builtin = True
    kb.pinned = True
    await session.commit()
    await session.refresh(kb)
    return kb


# ---------- 向量索引（后台补齐，失败不影响启动） ----------


def _resolve_source_path(raw_path: str) -> Path | None:
    path = Path(raw_path)
    if path.is_absolute():
        return path if path.exists() else None
    candidates = [Path.cwd() / path, Path.cwd().parent / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


async def seed_builtin_vectors() -> None:
    """为演示库补齐 Wiki / 素材向量，保证检索与问答开箱可用。"""
    from app.services import qdrant_store
    from app.services.embedder import embed_texts_async
    from app.services.splitter import split_markdown

    try:
        async with async_session_factory() as session:
            kb = (
                await session.execute(
                    select(KnowledgeBase).where(KnowledgeBase.builtin_key == BUILTIN_KEY)
                )
            ).scalars().first()
            if kb is None:
                return
            pages = (
                (
                    await session.execute(
                        select(WikiPage).where(WikiPage.kb_id == kb.id)
                    )
                )
                .scalars()
                .all()
            )
            sources = (
                (
                    await session.execute(
                        select(Source).where(Source.kb_id == kb.id)
                    )
                )
                .scalars()
                .all()
            )
            model = kb.embedding_model or settings.embed_model

            client = qdrant_store.get_client()
            wiki_collection = qdrant_store.wiki_collection(model)
            raw_collection = qdrant_store.raw_collection(model)
            wiki_count = (
                client.count(
                    collection_name=wiki_collection,
                    count_filter=qdrant_store.kb_filter(kb.id),
                    exact=True,
                ).count
                if client.collection_exists(wiki_collection)
                else 0
            )
            raw_count = (
                client.count(
                    collection_name=raw_collection,
                    count_filter=qdrant_store.kb_filter(kb.id),
                    exact=True,
                ).count
                if client.collection_exists(raw_collection)
                else 0
            )

            if wiki_count == 0 and pages:
                texts = [f"{p.title}\n{(p.body_md or '')[:2000]}" for p in pages]
                vectors = await embed_texts_async(texts, model)
                for page in pages:
                    qdrant_store.delete_wiki_page(kb.id, page.id, model)
                qdrant_store.upsert_wiki_pages(
                    kb.id,
                    [
                        {
                            "vector": vector,
                            "payload": {
                                "page_id": str(page.id),
                                "title": page.title,
                                "slug": page.slug,
                                "body_head": (page.body_md or "")[:500],
                                "human_edited": bool(page.human_edited),
                            },
                        }
                        for page, vector in zip(pages, vectors, strict=True)
                    ],
                    model,
                )
                logger.info("内置演示库 Wiki 向量已补齐：%d 页", len(pages))

            if raw_count == 0 and sources:
                total = 0
                for source in sources:
                    path = _resolve_source_path(source.raw_path)
                    if path is None:
                        logger.warning("演示素材文件缺失：%s", source.raw_path)
                        continue
                    chunks = split_markdown(path.read_text(encoding="utf-8"))
                    if not chunks:
                        continue
                    vectors = await embed_texts_async(
                        [chunk["content"] for chunk in chunks], model
                    )
                    qdrant_store.delete_source_chunks(source.id, model)
                    qdrant_store.upsert_chunks(
                        kb.id,
                        [
                            {
                                "vector": vector,
                                "payload": {
                                    "source_id": str(source.id),
                                    "chunk_index": index,
                                    "title": chunk["title"],
                                    "text": chunk["content"],
                                    "source_title": source.title,
                                },
                            }
                            for index, (chunk, vector) in enumerate(
                                zip(chunks, vectors, strict=True)
                            )
                        ],
                        model,
                    )
                    total += len(chunks)
                logger.info("内置演示库素材向量已补齐：%d 块", total)
    except Exception as exc:  # noqa: BLE001
        logger.warning("内置演示库向量补齐失败（检索将在后续重试）：%s", exc)


def start_vector_seed_task() -> asyncio.Task[None]:
    task = asyncio.create_task(seed_builtin_vectors())
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return task
