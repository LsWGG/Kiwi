"""Wiki 编译产物的清理：清空 / 重建与「删除全部已编译数据」。

编译产物包括：

- Wiki 页面及其向量、页面批注、Lint 报告；
- 笔记上的 ``wiki_page_id`` / ``wiki_links`` 软关联；
- 笔记快照 Source（``external_id = note:<id>``）与 raw 向量；
- 排队中的编译任务（避免删除后又被后台任务重新建页）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    IngestJob,
    Job,
    KnowledgeBase,
    LearningAnnotation,
    Note,
    Source,
    WikiLintReport,
    WikiPage,
)
from app.services.source_paths import resolve_raw_path

logger = logging.getLogger("kiwi.compiled_data")


async def clear_wiki_content(
    session: AsyncSession, kb: KnowledgeBase
) -> tuple[int, int, int]:
    """删除知识库的全部 Wiki 页、向量、健康报告与页面批注。

    返回 ``(页面数, 批注数, 健康报告数)``。笔记上的 ``wiki_page_id`` /
    ``wiki_links`` 只是 props 里的软关联，必须同步清空；回收站与归档笔记也
    要清理，避免恢复后继续指向已删除页面。
    """
    pages = list(
        (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb.id)))
        .scalars()
        .all()
    )
    from app.services import qdrant_store as qs

    # 覆盖当前与历史 embedding 模型下的全部 wiki collection。
    try:
        await asyncio.to_thread(qs.delete_wiki_vectors, kb.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("清空 Wiki 向量失败 %s：%s", kb.id, exc)

    notes = list(
        (await session.execute(select(Note).where(Note.kb_id == kb.id))).scalars().all()
    )
    for note in notes:
        props = dict(note.props_json or {})
        if "wiki_page_id" in props or "wiki_links" in props:
            props.pop("wiki_page_id", None)
            props.pop("wiki_links", None)
            note.props_json = props

    annotations = await session.execute(
        delete(LearningAnnotation).where(
            LearningAnnotation.kb_id == kb.id,
            LearningAnnotation.target_type == "wiki",
        )
    )
    reports = await session.execute(
        delete(WikiLintReport).where(WikiLintReport.kb_id == kb.id)
    )
    await session.execute(
        delete(WikiPage)
        .where(WikiPage.kb_id == kb.id)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return len(pages), annotations.rowcount or 0, reports.rowcount or 0


async def _delete_note_snapshot_sources(
    session: AsyncSession, kb_id: uuid.UUID
) -> int:
    """删除编译时为笔记生成的快照素材（正文仍以笔记为准，下次编译会重建）。"""
    sources = list(
        (
            await session.execute(
                select(Source).where(
                    Source.kb_id == kb_id,
                    or_(
                        Source.type == "note",
                        Source.external_id.like("note:%"),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    if not sources:
        return 0
    from app.services import qdrant_store as qs

    for source in sources:
        try:
            await asyncio.to_thread(qs.delete_source_chunks, source.id, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除笔记快照向量失败 %s：%s", source.id, exc)
        path = resolve_raw_path(source.raw_path) if source.raw_path else None
        if path and path.name.startswith("note-") and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
    ids = [source.id for source in sources]
    # 先解除笔记对 Source 的软引用（若仍有），再删除 Source（级联 IngestJob）。
    await session.execute(
        update(Note)
        .where(Note.kb_id == kb_id, Note.source_id.in_(ids))
        .values(source_id=None)
    )
    await session.execute(
        delete(Source)
        .where(Source.id.in_(ids))
        .execution_options(synchronize_session=False)
    )
    return len(ids)


async def delete_all_compiled_data(
    session: AsyncSession, kb: KnowledgeBase
) -> dict[str, int]:
    """删除当前知识库的全部编译数据，保留原始笔记与导入材料。"""
    now = datetime.now(timezone.utc)

    # 1. 终止排队 / 运行中的编译任务，防止清空后又被重新建页。
    cancelled_jobs = await session.execute(
        update(Job)
        .where(
            Job.kb_id == kb.id,
            Job.kind == "note_compile",
            Job.status.in_(("pending", "running")),
        )
        .values(
            status="cancelled",
            finished_at=now,
            message="已删除全部编译数据",
        )
    )
    await session.execute(
        update(IngestJob)
        .where(
            IngestJob.kb_id == kb.id,
            IngestJob.kind == "compile",
            IngestJob.status.in_(("pending", "running")),
        )
        .values(status="failed", error="已删除全部编译数据")
    )

    # 2. Wiki 页面 / 向量 / 批注 / Lint / 笔记软关联。
    pages, annotations, reports = await clear_wiki_content(session, kb)

    # 3. 笔记快照素材与向量。
    snapshots = await _delete_note_snapshot_sources(session, kb.id)

    # 4. 导入素材回到「已解析」状态，统计不再显示为已编译。
    sources = await session.execute(
        update(Source)
        .where(
            Source.kb_id == kb.id,
            Source.type != "note",
            Source.status == "compiled",
        )
        .values(status="parsed")
    )

    # 5. 清除定时编译水位，下一次编译不会因为「没有更新」而跳过。
    kb.wiki_compile_last_at = None
    kb.wiki_compile_last_status = {}
    await session.flush()

    return {
        "deleted_pages": pages,
        "cleared_annotations": annotations,
        "cleared_lint_reports": reports,
        "deleted_snapshots": snapshots,
        "cancelled_jobs": cancelled_jobs.rowcount or 0,
        "reset_sources": sources.rowcount or 0,
    }
