"""异步摄入编排：parse → chunk → embed → store → (可选)编译。

单用户、单进程：asyncio.create_task 后台执行，进度经 EventHub→SSE 推送。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from app.config import settings
from app.db.models import IngestJob, Job, KnowledgeBase, Note, Source, WikiPage
from app.db.session import async_session_factory
from app.event_hub import hub
from app.services import job_queue, qdrant_store
from app.services.embedder import embed_texts_async
from app.services.metrics import compile_job
from app.services.ocr_formatter import format_ocr_document
from app.services.parser import ParseError, parse_file
from app.services.source_paths import resolve_raw_path
from app.services.splitter import split_markdown
from app.services.wiki_compiler import CompileError, compile_source

logger = logging.getLogger(__name__)

# 全局任务注册表（job_id -> asyncio.Task）
_running: dict[str, asyncio.Task] = {}

# 「编译全部笔记」可能一次提交很多任务；限制同时调用 LLM 的编译数，
# 避免瞬间打满供应商速率限制。解析、嵌入仍可并行。
_compile_semaphore = asyncio.Semaphore(2)


def _content_fingerprint(data: bytes) -> str:
    return sha256(data).hexdigest()


async def _update_job(job_id: str, **fields) -> None:
    """更新 ingest_jobs 表。"""
    from sqlalchemy import update

    async with async_session_factory() as db:
        await db.execute(
            update(IngestJob).where(IngestJob.id == uuid.UUID(job_id)).values(**fields)
        )
        await db.commit()


async def _emit(job_id: str, e_type: str, payload: dict) -> None:
    await hub.publish(job_id, {"type": e_type, "payload": payload})


async def _enqueue_ingest(
    job_id: uuid.UUID,
    kb_id: uuid.UUID,
    *,
    mode: str,
    source_id: uuid.UUID | None = None,
    note_id: uuid.UUID | None = None,
    compile_now: bool = False,
    embed_raw: bool = True,
    use_ocr: bool = False,
) -> None:
    """把摄入执行写入持久化队列；幂等键与 IngestJob 一一对应。"""
    await job_queue.enqueue(
        "ingest",
        {
            "ingest_job_id": str(job_id),
            "kb_id": str(kb_id),
            "mode": mode,
            "source_id": str(source_id) if source_id else None,
            "note_id": str(note_id) if note_id else None,
            "compile_now": compile_now,
            "embed_raw": embed_raw,
            "use_ocr": use_ocr,
        },
        kb_id=kb_id,
        ref_id=str(job_id),
        idempotency_key=f"ingest:{job_id}",
    )


async def _update_import_note(
    note_id: uuid.UUID,
    *,
    status: str | None = None,
    progress: float | None = None,
    error: str | None = None,
    source_id: uuid.UUID | None = None,
    parsed=None,
    raw_stem: str | None = None,
) -> None:
    """把导入进度与解析正文写回工作区笔记（JSONB 必须整体赋值）。"""
    from datetime import datetime, timezone

    async with async_session_factory() as db:
        note = await db.get(Note, note_id)
        if note is None:
            return
        props = dict(note.props_json or {})
        imp = dict(props.get("import") or {})
        if status is not None:
            imp["status"] = status
        if progress is not None:
            imp["progress"] = round(float(progress), 3)
        if error is not None:
            imp["error"] = error
        if source_id is not None:
            note.source_id = source_id
            imp["source_id"] = str(source_id)
        if parsed is not None:
            imp["parse_quality"] = parsed.parse_quality
            if parsed.parse_quality == "review":
                imp["warning"] = "解析质量存疑，可能为扫描件或复杂版式"
            title = (parsed.title or "").strip()
            raw_stem = raw_stem or ""
            if (
                imp.get("title_source") != "user"
                and title
                and title != raw_stem
                and not raw_stem.startswith(title)
            ):
                note.title = title[:300]
            note.body_md = parsed.text or ""
        imp["updated_at"] = datetime.now(timezone.utc).isoformat()
        props["import"] = imp
        note.props_json = props
        await db.commit()


async def _process_note_from_existing_source(
    job_id: str,
    source_id: uuid.UUID,
    note_id: uuid.UUID,
    *,
    use_ocr: bool = False,
) -> None:
    """重复文件：复用已有 Source，只解析并填充笔记，不重复向量化。"""
    from sqlalchemy import select, update

    async def fail(msg: str) -> None:
        await _update_job(job_id, status="failed", error=msg)
        await _update_import_note(note_id, status="failed", error=msg)
        await _emit(job_id, "error", {"message": msg})
        logger.error("note import %s failed: %s", job_id, msg)

    try:
        await _update_job(job_id, status="running", progress=0.1)
        async with async_session_factory() as db:
            source = (
                await db.execute(select(Source).where(Source.id == source_id))
            ).scalar_one()
            source_type = source.type
            raw_path = resolve_raw_path(source.raw_path)
            kb_id = source.kb_id

        parsed = await asyncio.to_thread(
            parse_file, raw_path, source_type, force_ocr=use_ocr
        )
        parsed = await format_ocr_document(parsed, kb_id)
        await _update_import_note(
            note_id,
            source_id=source_id,
            parsed=parsed,
            raw_stem=Path(raw_path).stem,
            status="parsing",
            progress=0.6,
        )
        await _update_job(job_id, progress=1.0, status="succeeded")
        await _update_import_note(note_id, status="ready", progress=1.0)
        async with async_session_factory() as db:
            await db.execute(
                update(Source)
                .where(Source.id == source_id)
                .values(status="parsed")
            )
            await db.commit()
        await _emit(
            job_id,
            "done",
            {"source_id": str(source_id), "chunk_count": 0, "compiled": False, "deduped": True},
        )
    except (ParseError, CompileError) as e:
        await fail(str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("note import %s unexpected error", job_id)
        await fail(f"未知错误：{e}")
    finally:
        _running.pop(job_id, None)


async def run_ingest(
    file_bytes: bytes,
    filename: str,
    kb: KnowledgeBase,
    compile_now: bool = False,
    note_id: uuid.UUID | None = None,
    *,
    external_id: str | None = None,
    source_url: str = "",
    content_updated_at=None,
    batch_id: str | None = None,
    scan_status: str = "unavailable",
    scan_detail: str = "",
    source_type: str | None = None,
    title: str | None = None,
    use_ocr: bool = False,
) -> uuid.UUID:
    """启动后台 ingest 任务并返回 job_id。

    note_id 非空时走「导入到工作区笔记」分支：解析完成后把正文写回笔记；
    重复文件复用已有 Source，仅解析填充，不重复向量化。

    external_id 用于语雀等外部来源的增量重导入：内容变化时复用同一 Source，
    清空旧向量后重新入库；内容未变化则抛 FileExistsError（批次记为 skipped）。
    """
    from datetime import datetime, timezone

    # 指纹去重（事务级咨询锁避免并发重复上传）
    fp = _content_fingerprint(file_bytes)
    async with async_session_factory() as db:
        from sqlalchemy import select, text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:fp))"), {"fp": fp}
        )

        suffix = Path(filename).suffix or ".bin"
        rel = Path(settings.upload_dir) / str(kb.id)
        rel.mkdir(parents=True, exist_ok=True)
        rel_path = rel / f"{fp[:16]}{suffix}"

        if external_id:
            existing_external = (
                (
                    await db.execute(
                        select(Source).where(
                            Source.kb_id == kb.id, Source.external_id == external_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing_external is not None:
                if existing_external.sha256 == fp and existing_external.status in (
                    "parsed",
                    "compiled",
                ):
                    if note_id is None:
                        raise FileExistsError(
                            f"外部文档内容未变化（{existing_external.title}），已跳过"
                        )
                    job = IngestJob(
                        kb_id=kb.id,
                        source_id=existing_external.id,
                        kind="import",
                        status="pending",
                        note_id=note_id,
                        import_batch_id=batch_id,
                    )
                    db.add(job)
                    await db.commit()
                    job_id = job.id
                    await _enqueue_ingest(
                        job_id,
                        kb.id,
                        mode="existing_source",
                        source_id=existing_external.id,
                        note_id=note_id,
                        use_ocr=use_ocr,
                    )
                    return job_id
                old_path = Path(existing_external.raw_path)
                rel_path.write_bytes(file_bytes)
                existing_external.type = (
                    source_type or suffix.lstrip(".").lower() or "md"
                )
                existing_external.title = title or filename
                existing_external.raw_path = str(rel_path)
                existing_external.sha256 = fp
                existing_external.status = "received"
                existing_external.parse_quality = "clean"
                existing_external.parse_engine = "native"
                existing_external.quality_report = {}
                existing_external.scan_status = scan_status
                existing_external.scan_detail = scan_detail
                existing_external.source_url = source_url
                existing_external.content_updated_at = content_updated_at
                if batch_id:
                    existing_external.import_batch_id = batch_id
                source_id = existing_external.id
                # 源内容变化：给引用该素材的人工编辑页打「源漂移」标记，
                # 编译不会覆盖人工内容，由用户核对后决定是否重新编译。
                drift_pages = (
                    (
                        await db.execute(
                            select(WikiPage).where(
                                WikiPage.kb_id == kb.id,
                                WikiPage.human_edited.is_(True),
                                WikiPage.compiled_from_source_ids.contains(
                                    [str(source_id)]
                                ),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                drift_at = datetime.now(timezone.utc).isoformat()
                for drift_page in drift_pages:
                    fm = dict(drift_page.frontmatter_json or {})
                    fm["source_drift"] = {
                        "source_id": str(source_id),
                        "source_title": existing_external.title,
                        "detected_at": drift_at,
                    }
                    drift_page.frontmatter_json = fm
                if old_path != rel_path:
                    try:
                        old_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                job = IngestJob(
                    kb_id=kb.id,
                    source_id=source_id,
                    kind="recompile",
                    status="pending",
                    note_id=note_id,
                    import_batch_id=batch_id,
                )
                db.add(job)
                await db.commit()
                job_id = job.id
                await _enqueue_ingest(
                    job_id,
                    kb.id,
                    mode="ingest",
                    source_id=source_id,
                    note_id=note_id,
                    compile_now=compile_now,
                    use_ocr=use_ocr,
                )
                return job_id

        existed = (
            (await db.execute(select(Source).where(Source.kb_id == kb.id, Source.sha256 == fp)))
            .scalars()
            .first()
        )
        if existed:
            if note_id is None:
                raise FileExistsError(f"该文件已在此知识库中存在（{existed.title}）")
            # 共享数据库 / 迁移场景下，旧记录的 raw_path 可能指向另一个环境，
            # 或仍是相对路径。本次上传的字节就是权威内容，重新落到当前
            # upload_dir 并修正路径，避免解析时报「文件不存在」。
            rel_path.write_bytes(file_bytes)
            existed.raw_path = str(rel_path)
            job = IngestJob(
                kb_id=kb.id,
                source_id=existed.id,
                kind="import",
                status="pending",
                note_id=note_id,
                import_batch_id=batch_id,
            )
            db.add(job)
            await db.commit()
            job_id = job.id
            await _enqueue_ingest(
                job_id,
                kb.id,
                mode="existing_source",
                source_id=existed.id,
                note_id=note_id,
                use_ocr=use_ocr,
            )
            return job_id

        # 落盘原始素材（不可变）
        rel_path.write_bytes(file_bytes)

        source = Source(
            kb_id=kb.id,
            type=source_type or suffix.lstrip(".").lower() or "md",
            title=title or filename,
            raw_path=str(rel_path),
            sha256=fp,
            status="received",
            parse_engine="native",
            quality_report={},
            scan_status=scan_status,
            scan_detail=scan_detail,
            external_id=external_id,
            source_url=source_url,
            content_updated_at=content_updated_at,
            import_batch_id=batch_id
            or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        )
        db.add(source)
        await db.flush()
        source_id = source.id

        job = IngestJob(
            kb_id=kb.id,
            source_id=source_id,
            kind="import" if note_id else "ingest",
            status="pending",
            note_id=note_id,
            import_batch_id=batch_id,
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    await _enqueue_ingest(
        job_id,
        kb.id,
        mode="ingest",
        source_id=source_id,
        note_id=note_id,
        compile_now=compile_now,
        use_ocr=use_ocr,
    )
    return job_id


async def _process_ingest(
    job_id: str,
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    compile_now: bool,
    note_id: uuid.UUID | None = None,
    embed_raw: bool = True,
    use_ocr: bool = False,
) -> None:
    """执行摄入流水线。"""

    async def fail(msg: str) -> None:
        await _update_job(job_id, status="failed", error=msg)
        from sqlalchemy import update

        async with async_session_factory() as db:
            await db.execute(
                update(Source).where(Source.id == source_id).values(status="failed")
            )
            await db.commit()
        if note_id is not None:
            await _update_import_note(note_id, status="failed", error=msg)
        await _emit(job_id, "error", {"message": msg})
        logger.error("ingest %s failed: %s", job_id, msg)

    try:
        await _update_job(job_id, status="running", progress=0.05)
        # 取素材与知识库
        async with async_session_factory() as db:
            from sqlalchemy import select

            source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one()
            kb = (
                await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
            ).scalar_one()
            raw_path = resolve_raw_path(source.raw_path)

        await _emit(job_id, "parse_progress", {"status": "starting"})
        parsed = await asyncio.to_thread(
            parse_file, raw_path, source.type, force_ocr=use_ocr
        )
        parsed = await format_ocr_document(parsed, kb.id)
        await _update_job(job_id, progress=0.2)
        if note_id is not None:
            # 解析完先落正文，前端可立即阅读，向量化在后台继续
            await _update_import_note(
                note_id,
                source_id=source_id,
                parsed=parsed,
                raw_stem=raw_path.stem,
                status="parsing",
                progress=0.25,
            )
        if parsed.parse_quality == "review":
            async with async_session_factory() as db:
                from sqlalchemy import update

                await db.execute(
                    update(Source)
                    .where(Source.id == source_id)
                    .values(
                        status="parsed",
                        parse_quality="review",
                        parsed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()

        # 分块
        await _emit(job_id, "chunk_progress", {"status": "chunking"})
        chunks = split_markdown(parsed.text)
        await _update_job(job_id, progress=0.3)
        if note_id is not None:
            await _update_import_note(note_id, progress=0.35)
        await _emit(job_id, "chunk_done", {"chunk_count": len(chunks), "title": parsed.title})

        if embed_raw:
            model = kb.embedding_model or settings.embed_model
            # 重新导入时先清空该素材旧向量，避免重复 chunk 累积
            qdrant_store.delete_source_chunks(source_id, model)
            # 嵌入（按知识库配置的模型）
            await _emit(job_id, "embed_progress", {"status": "embedding", "total": len(chunks)})
            texts = [c["content"] for c in chunks]
            vecs = await embed_texts_async(texts, model)
            await _update_job(job_id, progress=0.6)

            # 入库 raw_chunks
            points = [
                {
                    "vector": v,
                    "payload": {
                        "source_id": str(source_id),
                        "chunk_index": i,
                        "title": chunks[i]["title"],
                        "text": chunks[i]["content"],
                        "source_title": parsed.title,
                    },
                }
                for i, v in enumerate(vecs)
            ]
            qdrant_store.upsert_chunks(kb_id, points, model)
        # 编译任务复用已入库的向量，不重复写入
        await _update_job(
            job_id, progress=0.8, status="succeeded" if not compile_now else "running"
        )
        if note_id is not None:
            await _update_import_note(note_id, progress=0.85)

        if compile_now:
            # 入库后直接编译；批量编译时限制并发，避免同时打满 LLM 配额。
            await _emit(job_id, "compile_progress", {"status": "compiling"})
            async with _compile_semaphore:
                async with compile_job():
                    result = await compile_source(uuid.UUID(job_id), source_id, kb, chunks)
            await _update_job(
                job_id,
                progress=1.0,
                status="succeeded",
                touched_page_ids=result["touched_page_ids"],
            )
        else:
            await _update_job(job_id, progress=1.0, status="succeeded")

        if note_id is not None:
            await _update_import_note(note_id, status="ready", progress=1.0)

        async with async_session_factory() as db:
            from sqlalchemy import update

            await db.execute(
                update(Source)
                .where(Source.id == source_id)
                .values(
                    status="compiled" if compile_now else "parsed",
                    parse_quality=parsed.parse_quality,
                    parse_engine=parsed.parse_engine,
                    quality_report={
                        **parsed.quality_report,
                        "warnings": parsed.warnings,
                    },
                    parsed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

        await _emit(
            job_id,
            "done",
            {
                "source_id": str(source_id),
                "chunk_count": len(chunks),
                "compiled": compile_now,
            },
        )
    except FileExistsError:
        await fail("重复内容：该素材已入库（或在后台去重命中）")
    except (ParseError, CompileError) as e:
        await fail(str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest %s unexpected error", job_id)
        await fail(f"未知错误：{e}")
    finally:
        _running.pop(job_id, None)


async def cancel_job(job_id: str) -> None:
    """取消摄入任务：同步取消持久化 Job（worker 会中断执行中的协程）。"""
    from sqlalchemy import select

    async with async_session_factory() as db:
        durable = (
            await db.execute(
                select(Job).where(Job.idempotency_key == f"ingest:{job_id}")
            )
        ).scalar_one_or_none()
    if durable is not None:
        await job_queue.cancel(durable.id)
    task = _running.get(job_id)
    if task and not task.done():
        task.cancel()
