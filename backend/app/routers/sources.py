"""素材路由。"""

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestJob, KnowledgeBase, Source
from app.db.session import get_session
from app.schemas.source import SourceOut, SourcePreviewOut
from app.services import ingest_service, qdrant_store
from app.services.parser import parse_file

logger = logging.getLogger(__name__)

PREVIEW_LIMIT = 400_000

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[SourceOut])
async def list_sources(
    kb_id: uuid.UUID,
    status: str | None = None,
    batch_id: uuid.UUID | None = None,
    include_notes: bool = False,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Source).where(Source.kb_id == kb_id).order_by(Source.created_at.desc())
    # 笔记编译会生成内部 Source；默认不混入用户导入的素材列表。
    if not include_notes:
        stmt = stmt.where(Source.type != "note")
    if status:
        stmt = stmt.where(Source.status == status)
    if batch_id:
        stmt = stmt.where(Source.import_batch_id == str(batch_id))
    rows = (await session.execute(stmt)).scalars().all()
    return [SourceOut.model_validate(s, from_attributes=True) for s in rows]


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    src = await session.get(Source, source_id)
    if src is None or src.kb_id != kb_id:
        raise HTTPException(404, "素材不存在")
    return SourceOut.model_validate(src, from_attributes=True)


@router.get("/{source_id}/preview", response_model=SourcePreviewOut)
async def preview_source(
    source_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """读取素材原文（重新解析，不落库），供引用块「查看原文」跳转与高亮。"""
    src = await session.get(Source, source_id)
    if src is None or src.kb_id != kb_id:
        raise HTTPException(404, "素材不存在")
    path = Path(src.raw_path)
    if not path.exists():
        raise HTTPException(404, "素材原文件已不存在")

    text = ""
    engine = src.parse_engine
    try:
        parsed = await asyncio.to_thread(parse_file, path, src.type)
        text = parsed.text or ""
        engine = parsed.parse_engine
    except Exception as e:  # noqa: BLE001 - 解析失败时对文本类素材降级直读
        if src.type in ("md", "markdown", "txt"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as read_error:
                raise HTTPException(500, f"读取素材失败：{read_error}") from read_error
        else:
            raise HTTPException(422, f"素材原文解析失败：{e}") from e

    truncated = len(text) > PREVIEW_LIMIT
    return SourcePreviewOut(
        id=src.id,
        kb_id=src.kb_id,
        title=src.title,
        type=src.type,
        sha256=src.sha256,
        source_url=src.source_url,
        parse_quality=src.parse_quality,
        parse_engine=engine,
        text=text[:PREVIEW_LIMIT],
        truncated=truncated,
    )


@router.post("/{source_id}/reparse", status_code=202)
async def reparse_source(
    source_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """重新解析素材：OCR 置信度低、解析失败或解析器升级后重跑流水线。

    原文文件不变，因此不新建 Source；旧向量会在流水线内先清空再写入。
    """
    src = await session.get(Source, source_id)
    if src is None or src.kb_id != kb_id:
        raise HTTPException(404, "素材不存在")
    if src.status in ("received", "parsing"):
        raise HTTPException(409, "素材正在处理中，请稍后再试")

    running = (
        await session.execute(
            select(IngestJob).where(
                IngestJob.source_id == source_id,
                IngestJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if running is not None:
        raise HTTPException(409, "该素材已有进行中的任务")

    src.status = "received"
    src.parse_quality = "clean"
    src.parse_engine = "native"
    src.quality_report = {}
    job = IngestJob(kb_id=kb_id, source_id=src.id, kind="reparse", status="pending")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    ingest_service._running[str(job.id)] = asyncio.create_task(
        ingest_service._process_ingest(
            str(job.id), kb_id, src.id, compile_now=False, embed_raw=True
        ),
        name=f"reparse:{job.id}",
    )
    return {"job_id": str(job.id), "status": "pending"}


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    src = await session.get(Source, source_id)
    if src is None or src.kb_id != kb_id:
        raise HTTPException(404, "素材不存在")
    kb = await session.get(KnowledgeBase, kb_id)
    raw_path = Path(src.raw_path)
    await session.delete(src)
    await session.commit()

    # 派生数据清理：向量索引可重建，但不该留下孤儿 chunk。
    try:
        await asyncio.to_thread(
            qdrant_store.delete_source_chunks,
            source_id,
            kb.embedding_model if kb else None,
        )
    except Exception:  # noqa: BLE001 - 向量库不可用时不应阻塞素材删除
        logger.warning("删除素材 %s 的向量失败", source_id, exc_info=True)
    try:
        raw_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("删除素材原文件失败：%s", raw_path, exc_info=True)
