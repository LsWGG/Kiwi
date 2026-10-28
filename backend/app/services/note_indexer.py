"""笔记向量索引：让问答可以直接检索 Wiki 与工作区笔记。

笔记是原始素材经过整理后的最终形态，因此问答不再检索 ``raw_chunks``。
索引采用「按需核对 + 后台巡检」：

- 启动后与每次问答前，对比笔记的 ``updated_at``（数据表还包含行与行笔记的
  更新时间）与 Qdrant payload 中记录的版本；只有变化的笔记才重新分块、嵌入。
- 后台巡检定期清理已删除 / 回收站笔记的向量，并补齐漏索引内容。
- 向量写入独立的 ``note_chunks`` collection，按 embedding 模型分区，
  与 Wiki、素材向量互不影响。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CollectionRow, KnowledgeBase, Note, NoteCollection
from app.db.session import async_session_factory
from app.services import note_compiler, qdrant_store
from app.services.embedder import embed_texts_async, is_disabled
from app.services.splitter import split_markdown

logger = logging.getLogger("kiwi.note_index")

RECONCILE_INTERVAL_SECONDS = 300
MAX_CHUNKS_PER_NOTE = 200
KIND_LABEL = {
    "doc": "文档",
    "import": "导入文档",
    "database": "数据表",
    "canvas": "画布",
    "notebook": "Notebook",
    "link": "链接笔记",
}

# (collection, note_id) → (所属 kb_id, 笔记内容版本)
_versions: dict[tuple[str, str], tuple[uuid.UUID, str]] = {}
# 已从 Qdrant 载入过版本信息的 (collection, kb_id)
_loaded: set[tuple[str, uuid.UUID]] = set()
_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _kb_lock(kb_id: uuid.UUID) -> asyncio.Lock:
    lock = _locks.get(kb_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[kb_id] = lock
    return lock


def _version_key(collection: str, note_id: uuid.UUID | str) -> tuple[str, str]:
    return collection, str(note_id)


def forget_kb(kb_id: uuid.UUID) -> None:
    """丢弃某知识库的内存索引版本缓存。

    删除 / 重建知识库（尤其是内置演示库复用固定 ID）后，Qdrant 中的向量
    已被清空，但内存缓存仍会认为内容未变化；必须清掉后才会重新嵌入。
    """
    for key in [key for key, (owner, _version) in _versions.items() if owner == kb_id]:
        _versions.pop(key, None)
    for key in [key for key in _loaded if key[1] == kb_id]:
        _loaded.discard(key)


def _stamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


async def _database_version(db: AsyncSession, note: Note) -> str:
    """数据表正文来自行数据与行笔记，必须把它们的变化纳入版本。"""
    coll_id = (
        await db.execute(
            select(NoteCollection.id).where(NoteCollection.note_id == note.id)
        )
    ).scalar_one_or_none()
    if coll_id is None:
        return ""
    row_count, row_updated = (
        await db.execute(
            select(func.count(CollectionRow.id), func.max(CollectionRow.updated_at)).where(
                CollectionRow.collection_id == coll_id
            )
        )
    ).one()
    child_updated = (
        await db.execute(
            select(func.max(Note.updated_at)).where(
                Note.id.in_(
                    select(CollectionRow.note_id).where(
                        CollectionRow.collection_id == coll_id,
                        CollectionRow.note_id.is_not(None),
                    )
                )
            )
        )
    ).scalar_one_or_none()
    return f"{coll_id}|{row_count}|{_stamp(row_updated)}|{_stamp(child_updated)}"


async def _note_version(db: AsyncSession, note: Note) -> str:
    base = _stamp(note.updated_at)
    if note.kind == "database":
        detail = await _database_version(db, note)
        if detail:
            return f"{base}|{detail}"
    return base


def _note_markdown(note: Note, body: str) -> str:
    """给正文补上标题，保证仅凭分块也能定位到笔记。"""
    title = (note.title or "").strip() or "未命名笔记"
    text = (body or "").strip()
    if not text:
        return f"# {title}"
    first_line = text.splitlines()[0].strip()
    if first_line == f"# {title}":
        return text
    return f"# {title}\n\n{text}"


async def _index_note(
    db: AsyncSession, note: Note, version: str, model: str | None
) -> int:
    """重新嵌入单条笔记，返回写入的分块数。"""
    body = await note_compiler.build_note_compile_markdown(db, note)
    markdown = _note_markdown(note, body)
    chunks = split_markdown(markdown)[:MAX_CHUNKS_PER_NOTE]
    title = (note.title or "").strip() or "未命名笔记"

    if not chunks:
        qdrant_store.delete_note_chunks(note.id, model)
        return 0

    texts = [f"{title}\n{chunk['content']}" for chunk in chunks]
    vectors = await embed_texts_async(texts, model)
    if len(vectors) != len(chunks):
        raise RuntimeError("嵌入返回的向量数量与分块数量不一致")

    # 先清旧向量，避免标题变化或分块减少后残留重复点。
    qdrant_store.delete_note_chunks(note.id, model)
    qdrant_store.upsert_note_chunks(
        note.kb_id,
        [
            {
                "vector": vector,
                "payload": {
                    "note_id": str(note.id),
                    "title": title,
                    "kind": note.kind,
                    "chunk_index": index,
                    "heading": str(chunk.get("title") or ""),
                    "text": chunk["content"],
                    "index_version": version,
                },
            }
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ],
        model,
    )
    return len(chunks)


def _load_versions(kb_id: uuid.UUID, collection: str, model: str | None) -> None:
    if (collection, kb_id) in _loaded:
        return
    for payload in qdrant_store.scroll_note_chunks(kb_id, model):
        note_id = str(payload.get("note_id") or "")
        version = str(payload.get("index_version") or "")
        if not note_id:
            continue
        _versions[_version_key(collection, note_id)] = (kb_id, version)
    _loaded.add((collection, kb_id))


def _drop_stale(
    kb_id: uuid.UUID, collection: str, active_ids: set[str], model: str | None
) -> int:
    removed = 0
    for key in [k for k in _versions if k[0] == collection]:
        owner_kb, _version = _versions[key]
        # 同一 collection 可能服务多个知识库；只清理属于当前库的失效笔记。
        if owner_kb != kb_id or key[1] in active_ids:
            continue
        try:
            qdrant_store.delete_note_chunks(key[1], model)
        except Exception:  # noqa: BLE001 —— 清理失败下次巡检重试
            logger.warning("清理笔记向量失败：%s", key[1], exc_info=True)
            continue
        _versions.pop(key, None)
        removed += 1
    return removed


async def ensure_notes_indexed(
    kb_ids: list[uuid.UUID], *, force: bool = False
) -> dict[str, int | bool]:
    """把范围内知识库的笔记同步到向量库，返回本次统计。

    问答在检索前调用它，保证刚编辑过的笔记也能被当前问题检索到。
    """
    if is_disabled():
        return {
            "indexed": 0,
            "skipped": 0,
            "deleted": 0,
            "failed": 0,
            "vectors_disabled": True,
        }
    stats = {"indexed": 0, "skipped": 0, "deleted": 0, "failed": 0}
    for kb_id in dict.fromkeys(kb_ids):
        async with _kb_lock(kb_id):
            async with async_session_factory() as db:
                kb = await db.get(KnowledgeBase, kb_id)
                if kb is None:
                    continue
                model = kb.embedding_model
                collection = qdrant_store.note_collection(model)
                try:
                    if (collection, kb_id) not in _loaded:
                        await asyncio.to_thread(_load_versions, kb_id, collection, model)
                except Exception:  # noqa: BLE001 —— Qdrant 暂不可用时跳过，不影响聊天
                    logger.warning("读取笔记索引版本失败（跳过本轮）：%s", kb_id, exc_info=True)
                    continue

                notes = list(
                    (
                        await db.execute(
                            select(Note).where(
                                Note.kb_id == kb_id,
                                Note.status == "active",
                                # 上锁笔记不进入问答检索；active_ids 不含它，
                                # 下方 _drop_stale 会顺带清掉历史向量。
                                Note.lock_hash.is_(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                active_ids = {str(note.id) for note in notes}
                for note in notes:
                    try:
                        version = await _note_version(db, note)
                    except Exception:  # noqa: BLE001
                        logger.warning("计算笔记版本失败：%s", note.id, exc_info=True)
                        stats["failed"] += 1
                        continue
                    key = _version_key(collection, note.id)
                    current = _versions.get(key)
                    if not force and current is not None and current[1] == version:
                        stats["skipped"] += 1
                        continue
                    try:
                        count = await _index_note(db, note, version, model)
                    except Exception:  # noqa: BLE001 —— 单条失败不阻断其它笔记
                        logger.warning("笔记索引失败：%s", note.id, exc_info=True)
                        stats["failed"] += 1
                        continue
                    _versions[key] = (kb_id, version)
                    stats["indexed"] += 1
                    if count == 0:
                        logger.debug("笔记无可索引正文，已清空向量：%s", note.id)

                stats["deleted"] += _drop_stale(kb_id, collection, active_ids, model)
    return stats


async def reconcile_all_notes() -> None:
    """后台巡检：覆盖全部知识库，清理失效向量并补齐变更。"""
    if is_disabled():
        return
    async with async_session_factory() as db:
        kb_ids = list((await db.execute(select(KnowledgeBase.id))).scalars().all())
    for kb_id in kb_ids:
        try:
            await ensure_notes_indexed([kb_id])
        except Exception:  # noqa: BLE001
            logger.warning("笔记索引巡检失败：%s", kb_id, exc_info=True)


async def _reconcile_loop() -> None:
    # 等启动阶段的内置演示库写入完成，避免两批嵌入同时争抢模型。
    await asyncio.sleep(8)
    while True:
        try:
            await reconcile_all_notes()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("笔记索引后台任务异常（稍后重试）", exc_info=True)
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)


def start_note_index_task() -> asyncio.Task[None]:
    task = asyncio.create_task(_reconcile_loop(), name="note-index-reconcile")
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return task
