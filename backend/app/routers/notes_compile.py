"""笔记到 Wiki 的编译。"""

import logging
import re
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    IngestJob,
    KnowledgeBase,
    Note,
    Source,
    WikiPage,
)
from app.db.session import async_session_factory, get_session
from app.routers.notes_shared import (
    _get_note,
    _require_unlocked,
)
from app.schemas.note import (
    NoteCompileOut,
    NoteCompileStatusOut,
)
from app.services import (
    job_queue,
    note_compiler,
)
from app.services.note_indexer import ensure_notes_indexed

logger = logging.getLogger("kiwi.notes.compile")

router = APIRouter()

# ---- 笔记 → Wiki 编译 ----

async def _prepare_note_compile(
    session: AsyncSession, kb_id: uuid.UUID, note: Note
) -> tuple[IngestJob, Source, bool] | None:
    """把任意类型的笔记序列化为 Source 并创建编译任务。

    - 同一笔记始终复用同一个 Source（external_id = note:<id>），不随正文变化堆积素材；
    - 正文未变化时跳过 raw 向量化；内容变化时重新嵌入后编译；
    - 已有进行中的编译任务时返回 None（单篇接口会转成 409）。
    """
    body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
    if not body:
        return None

    running = (
        await session.execute(
            select(IngestJob.id).where(
                IngestJob.kb_id == kb_id,
                IngestJob.note_id == note.id,
                IngestJob.kind == "compile",
                IngestJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if running is not None:
        return None

    content = body.encode("utf-8")
    fingerprint = sha256(content).hexdigest()
    external_id = f"note:{note.id}"

    source = (
        await session.execute(
            select(Source).where(
                Source.kb_id == kb_id, Source.external_id == external_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        # 兼容旧版按内容指纹创建的笔记素材：从该笔记最近一次编译任务回溯。
        last_job = (
            await session.execute(
                select(IngestJob)
                .where(
                    IngestJob.kb_id == kb_id,
                    IngestJob.note_id == note.id,
                    IngestJob.kind == "compile",
                )
                .order_by(IngestJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_job is not None:
            source = await session.get(Source, last_job.source_id)

    rel = Path(settings.upload_dir) / str(kb_id)
    rel.mkdir(parents=True, exist_ok=True)
    raw_path = rel / f"note-{note.id}.md"
    reused = bool(
        source is not None
        and source.sha256 == fingerprint
        and Path(source.raw_path).exists()
    )

    if source is None:
        raw_path.write_bytes(content)
        source = Source(
            kb_id=kb_id,
            type="note",
            title=(note.title or "笔记")[:300],
            raw_path=str(raw_path),
            sha256=fingerprint,
            status="parsed",
            parse_quality="clean",
            external_id=external_id,
            parsed_at=datetime.now(timezone.utc),
        )
        session.add(source)
        await session.flush()
    else:
        old_path = Path(source.raw_path)
        if not reused:
            raw_path.write_bytes(content)
            source.raw_path = str(raw_path)
            source.sha256 = fingerprint
        source.type = "note"
        source.external_id = external_id
        source.title = (note.title or "笔记")[:300]
        source.status = "parsed"
        source.parse_quality = "clean"
        source.parsed_at = datetime.now(timezone.utc)
        # 旧版本按指纹命名的临时原文，迁移到稳定路径后清理。
        if old_path != raw_path and old_path.exists() and old_path.name.startswith("note-"):
            try:
                old_path.unlink()
            except OSError:
                pass

    job = IngestJob(
        kb_id=kb_id,
        source_id=source.id,
        kind="compile",
        status="pending",
        note_id=note.id,
    )
    session.add(job)
    await session.flush()
    return job, source, reused


def _normalized_title(title: str) -> str:
    """归一化标题：去掉「示例项目 ·」这类前缀与空白 / 标点，便于匹配。"""
    text = str(title or "").strip()
    if "·" in text:
        text = text.rsplit("·", 1)[-1].strip()
    return re.sub(r"[\s\-_/·:：,，。()（）\[\]【】]+", "", text.lower())


def _pick_compiled_page(note_title: str, pages: list[WikiPage]) -> WikiPage | None:
    """从一次编译触达的页面中选出笔记的主页面。

    编译模型可能同时新建 / 更新多个页面，其中不少只是相关页面而非笔记本身。
    只在标题明确对应时关联，避免把「画布示例」错误挂到「Wiki」页面；无法
    判断时返回 None，宁可不展示入口也不产生误导。
    """
    title = _normalized_title(note_title)
    if not title:
        return pages[0] if len(pages) == 1 else None

    exact = [page for page in pages if _normalized_title(page.title) == title]
    if exact:
        return exact[0]

    related = [
        page
        for page in pages
        if len(_normalized_title(page.title)) >= 3
        and (
            title in _normalized_title(page.title)
            or _normalized_title(page.title) in title
        )
    ]
    if related:
        return max(related, key=lambda page: len(_normalized_title(page.title)))
    return pages[0] if len(pages) == 1 else None


async def _link_note_compiled_page(
    note_id: uuid.UUID | None, kb_id: uuid.UUID, job_id: uuid.UUID
) -> None:
    """编译成功后把笔记关联到主 Wiki 页面，供笔记详情与列表直接跳转。"""
    if note_id is None:
        return
    async with async_session_factory() as db:
        job = await db.get(IngestJob, job_id)
        if job is None or job.status != "succeeded":
            return
        page_ids = [
            uuid.UUID(str(raw))
            for raw in (job.touched_page_ids or [])
            if str(raw).strip()
        ]
        if not page_ids:
            return
        pages = list(
            (
                await db.execute(
                    select(WikiPage).where(
                        WikiPage.kb_id == kb_id, WikiPage.id.in_(page_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        note = await db.get(Note, note_id)
        if note is None or not pages:
            return
        chosen = _pick_compiled_page(note.title or "", pages)
        if chosen is None:
            return
        props = dict(note.props_json or {})
        if str(props.get("wiki_page_id") or "") == str(chosen.id):
            return
        props["wiki_page_id"] = str(chosen.id)
        note.props_json = props
        await db.commit()


async def _schedule_note_compile(
    job: IngestJob, kb_id: uuid.UUID, source_id: uuid.UUID, reused: bool
) -> None:
    """写入持久化队列；进程重启后 worker 会重新执行未完成的编译。"""
    await job_queue.enqueue(
        "note_compile",
        {
            "job_id": str(job.id),
            "kb_id": str(kb_id),
            "source_id": str(source_id),
            "note_id": str(job.note_id) if job.note_id else None,
            "reused": reused,
        },
        kb_id=kb_id,
        ref_id=str(job.id),
        idempotency_key=f"compile:{job.id}",
    )


@router.post("/reindex", response_model=dict)
async def reindex_notes(
    kb_id: uuid.UUID,
    force: bool = Query(False, description="忽略版本缓存，强制重建全部笔记向量"),
    session: AsyncSession = Depends(get_session),
):
    """重建知识库的笔记向量索引（问答检索使用）。

    正常情况下索引会随笔记编辑自动同步；该接口用于切换嵌入模型或排查
    检索异常后手动重建。
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    stats = await ensure_notes_indexed([kb_id], force=force)
    return {"kb_id": str(kb_id), **stats}


@router.post("/compile-all", response_model=dict, status_code=202)
async def compile_all_notes(
    kb_id: uuid.UUID,
    limit: int | None = Query(None, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """把工作区全部活跃笔记编译进 Wiki。

    默认不设上限，覆盖文档 / 导入 / 链接 / 数据表 / 画布 / Notebook；
    数据表行笔记随所属数据表一起编译，不重复提交。``limit`` 仅用于分批调用。
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")

    notes = list(
        (
            await session.execute(
                select(Note)
                .where(
                    Note.kb_id == kb_id,
                    Note.status == "active",
                    Note.lock_hash.is_(None),
                )
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    # 数据表行笔记随所属数据表一起编译；自动维护的待办收件箱不属于知识正文。
    candidates = [
        note
        for note in notes
        if not (note.props_json or {}).get("collection_row_id")
        and not (note.props_json or {}).get("todo_hub")
    ]
    jobs: list[dict] = []
    empty = 0
    busy = 0
    selected = 0
    for note in candidates:
        if limit is not None and len(jobs) >= limit:
            break
        selected += 1
        prepared = await _prepare_note_compile(session, kb_id, note)
        if prepared is None:
            body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
            if body:
                busy += 1
            else:
                empty += 1
            continue
        job, source, reused = prepared
        await session.commit()
        await _schedule_note_compile(job, kb_id, source.id, reused)
        jobs.append(
            {
                "job_id": str(job.id),
                "note_id": str(note.id),
                "note_title": note.title,
                "source_id": str(source.id),
            }
        )

    # 手动全量编译同样计入「最近编译」，避免卡片一直显示“尚未运行”，
    # 也让定时任务从本次编译之后继续增量处理。
    now = datetime.now(timezone.utc)
    kb.wiki_compile_last_at = now
    kb.wiki_compile_last_status = {
        "at": now.isoformat(),
        "trigger": "manual",
        "status": "scheduled",
        "scheduled": len(jobs),
        "candidates": len(candidates),
        "busy": busy,
        "empty": empty,
        "failed": 0,
    }
    await session.commit()
    return {
        "jobs": jobs,
        "count": len(jobs),
        "candidates": len(candidates),
        "skipped_empty": empty,
        "skipped_busy": busy,
        "skipped_limit": max(0, len(candidates) - selected),
    }


@router.post("/{note_id}/compile", response_model=NoteCompileOut, status_code=202)
async def compile_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """把笔记内容（含数据表 / 画布 / 链接）送入编译流水线。"""
    note = await _get_note(session, kb_id, note_id)
    _require_unlocked(note, x_note_token, "编译")
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")

    prepared = await _prepare_note_compile(session, kb_id, note)
    if prepared is None:
        body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
        if not body:
            raise HTTPException(400, "该笔记没有可编译的内容")
        raise HTTPException(409, "该笔记正在编译中，请稍后再试")

    job, source, reused = prepared
    job_id = job.id
    source_id = source.id
    await session.commit()
    await _schedule_note_compile(job, kb_id, source_id, reused)
    return NoteCompileOut(job_id=job_id, source_id=source_id, reused_source=reused)


@router.get("/{note_id}/compile/status", response_model=NoteCompileStatusOut)
async def note_compile_status(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _get_note(session, kb_id, note_id)
    job = (
        await session.execute(
            select(IngestJob)
            .where(
                IngestJob.kb_id == kb_id,
                IngestJob.note_id == note_id,
                IngestJob.kind == "compile",
            )
            .order_by(IngestJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return NoteCompileStatusOut()
    touched = job.touched_page_ids or []
    return NoteCompileStatusOut(
        job_id=job.id,
        status=job.status,
        progress=float(job.progress or 0.0),
        error=job.error,
        source_id=job.source_id,
        compiled=job.status == "succeeded",
        page_count=len(touched) if isinstance(touched, list) else 0,
        finished_at=job.updated_at,
    )


