"""知识库路由。"""

import re
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.config import settings
from app.db.models import (
    KnowledgeBase,
    Note,
    NoteAttachment,
    NoteFolder,
    NoteRevision,
    NoteTag,
    NoteTagLink,
    Source,
    StudyProfile,
    StudyReview,
    TodoMirror,
    WikiPage,
)
from app.db.session import get_session
from app.schemas.kb import (
    BuiltinKbStatus,
    KBCreate,
    KBDashboardActivity,
    KBDashboardCounts,
    KBDashboardDayNote,
    KBDashboardDayOut,
    KBDashboardOut,
    KBDashboardStudy,
    KBDashboardTag,
    KBImportOut,
    KBOut,
    KBOverview,
    KBReorderIn,
    KBUpdate,
)
from app.schemas.note import NoteSummary
from app.services import audit, kb_transfer, qdrant_store, todo_sync
from app.services.builtin_demo import (
    get_builtin_status,
    purge_builtin_kb,
    restore_builtin,
)
from app.services.embedder import is_disabled
from app.services.note_indexer import forget_kb
from app.services.notebook_kernel import kernel_manager

router = APIRouter(prefix="/api/kbs", tags=["kbs"])


async def _get_kb(
    session: AsyncSession, kb_id: uuid.UUID, *, include_deleted: bool = False
) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or (kb.deleted_at is not None and not include_deleted):
        raise HTTPException(404, "知识库不存在")
    return kb


def _slugify(name: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", name.lower()).strip("-")[:120]
    return s or "kb"


@router.get("", response_model=list[KBOverview])
async def list_kbs(session: AsyncSession = Depends(get_session)):
    rows = (
        (
            await session.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.deleted_at.is_(None))
                .order_by(
                    KnowledgeBase.pinned.desc(),
                    KnowledgeBase.sort_order,
                    KnowledgeBase.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    result = []
    for kb in rows:
        result.append(await _overview(session, kb))
    return result


async def _overview(session: AsyncSession, kb: KnowledgeBase) -> KBOverview:
    src = (
        await session.execute(select(func.count()).select_from(Source).where(Source.kb_id == kb.id))
    ).scalar_one()
    wiki = (
        await session.execute(
            select(func.count()).select_from(WikiPage).where(WikiPage.kb_id == kb.id)
        )
    ).scalar_one()
    notes = (
        await session.execute(select(func.count()).select_from(Note).where(Note.kb_id == kb.id))
    ).scalar_one()

    # 学习画像只读聚合（是否冷启动、掌握度覆盖率、到期复习）
    profile = (
        (await session.execute(select(StudyProfile).where(StudyProfile.kb_id == kb.id)))
        .scalars()
        .first()
    )
    mastery = dict(profile.mastery or {}) if profile else {}
    mastered = sum(1 for v in mastery.values() if float(v) >= 0.7)
    due_reviews = (
        await session.execute(
            select(func.count())
            .select_from(StudyReview)
            .where(
                StudyReview.kb_id == kb.id,
                StudyReview.due_at <= datetime.now(timezone.utc),
            )
        )
    ).scalar_one()
    todo_open = (
        await session.execute(
            select(func.count())
            .select_from(TodoMirror)
            .where(TodoMirror.kb_id == kb.id, TodoMirror.status == "open")
        )
    ).scalar_one()
    todo_done = (
        await session.execute(
            select(func.count())
            .select_from(TodoMirror)
            .where(TodoMirror.kb_id == kb.id, TodoMirror.status == "done")
        )
    ).scalar_one()

    # 最近活动：取笔记 / Wiki / 素材最近更新时间
    last_activity: datetime | None = kb.updated_at
    for column, model in (
        (Note.updated_at, Note),
        (WikiPage.updated_at, WikiPage),
        (Source.created_at, Source),
    ):
        value = (
            await session.execute(select(func.max(column)).where(model.kb_id == kb.id))
        ).scalar_one()
        if value and (last_activity is None or value > last_activity):
            last_activity = value

    return KBOverview(
        **{
            "id": kb.id,
            "name": kb.name,
            "slug": kb.slug,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "llm_config_id": kb.llm_config_id,
            "pinned": bool(kb.pinned),
            "learning_enabled": bool(kb.learning_enabled),
            "is_builtin": bool(kb.is_builtin),
            "builtin_key": kb.builtin_key,
            "deleted_at": kb.deleted_at,
            "sort_order": kb.sort_order,
            "wiki_compile_interval_hours": kb.wiki_compile_interval_hours,
            "wiki_compile_last_at": kb.wiki_compile_last_at,
            "wiki_compile_last_status": kb.wiki_compile_last_status or {},
            "todo_sync_interval_hours": kb.todo_sync_interval_hours,
            "todo_sync_last_at": kb.todo_sync_last_at,
            "created_at": kb.created_at,
            "updated_at": kb.updated_at,
        },
        source_count=src,
        wiki_count=wiki,
        note_count=notes,
        onboarded=bool(profile.onboarded) if profile else False,
        goal_type=profile.goal_type if profile else None,
        attempted_topics=len(mastery),
        mastered_topics=mastered,
        mastery_coverage=round(mastered / wiki, 3) if wiki else 0.0,
        due_reviews=int(due_reviews or 0),
        todo_open_count=int(todo_open or 0),
        todo_done_count=int(todo_done or 0),
        last_activity_at=last_activity,
    )


@router.get("/{kb_id}/dashboard", response_model=KBDashboardOut)
async def kb_dashboard(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """知识库总览：计数、近半年活动、标签分布与推荐笔记。

    只做只读聚合，不写任何业务数据；「常用」以近 90 天历史版本数量衡量，
    历史版本不足时用最近更新的笔记补齐，保证推荐列表始终可用。
    """
    kb = await _get_kb(session, kb_id)
    now = datetime.now(timezone.utc)
    active = (Note.kb_id == kb.id, Note.status == "active")

    kind_rows = (
        await session.execute(
            select(Note.kind, func.count()).where(*active).group_by(Note.kind)
        )
    ).all()
    by_kind = {str(kind): int(count) for kind, count in kind_rows}

    async def count_rows(*where) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(Note).where(*where)
                )
            ).scalar_one()
        )

    archived = await count_rows(Note.kb_id == kb.id, Note.status == "archived")
    trash = await count_rows(Note.kb_id == kb.id, Note.status == "trash")
    folders = int(
        (
            await session.execute(
                select(func.count())
                .select_from(NoteFolder)
                .where(NoteFolder.kb_id == kb.id)
            )
        ).scalar_one()
    )
    tags = int(
        (
            await session.execute(
                select(func.count()).select_from(NoteTag).where(NoteTag.kb_id == kb.id)
            )
        ).scalar_one()
    )
    attachments = int(
        (
            await session.execute(
                select(func.count())
                .select_from(NoteAttachment)
                .where(NoteAttachment.kb_id == kb.id)
            )
        ).scalar_one()
    )
    words = int(
        (
            await session.execute(
                select(
                    func.coalesce(func.sum(func.char_length(Note.body_md)), 0)
                ).where(*active)
            )
        ).scalar_one()
    )

    # 近 182 天活动：新建笔记 + 自动保存产生的历史版本。
    since = now - timedelta(days=182)
    revision_rows = (
        await session.execute(
            select(func.date(NoteRevision.created_at), func.count())
            .where(
                NoteRevision.kb_id == kb.id,
                NoteRevision.created_at >= since,
            )
            .group_by(func.date(NoteRevision.created_at))
        )
    ).all()
    created_rows = (
        await session.execute(
            select(func.date(Note.created_at), func.count())
            .where(*active, Note.created_at >= since)
            .group_by(func.date(Note.created_at))
        )
    ).all()
    activity_by_day: dict[date, int] = {}
    for day, count in (*revision_rows, *created_rows):
        if day is None:
            continue
        activity_by_day[day] = activity_by_day.get(day, 0) + int(count)
    activity = [
        KBDashboardActivity(date=day, count=count)
        for day, count in sorted(activity_by_day.items())
    ]

    tag_rows = (
        await session.execute(
            select(NoteTag.name, func.count(NoteTagLink.note_id))
            .join(NoteTagLink, NoteTagLink.tag_id == NoteTag.id)
            .join(Note, Note.id == NoteTagLink.note_id)
            .where(*active)
            .group_by(NoteTag.name)
            .order_by(func.count(NoteTagLink.note_id).desc(), NoteTag.name)
            .limit(10)
        )
    ).all()
    tag_stats = [KBDashboardTag(name=name, count=int(count)) for name, count in tag_rows]

    profile = (
        (await session.execute(select(StudyProfile).where(StudyProfile.kb_id == kb.id)))
        .scalars()
        .first()
    )
    mastery = dict(profile.mastery or {}) if profile else {}
    mastered = sum(1 for value in mastery.values() if float(value) >= 0.7)
    due_reviews = int(
        (
            await session.execute(
                select(func.count())
                .select_from(StudyReview)
                .where(
                    StudyReview.kb_id == kb.id,
                    StudyReview.due_at <= now,
                )
            )
        ).scalar_one()
    )
    todo_open = int(
        (
            await session.execute(
                select(func.count())
                .select_from(TodoMirror)
                .where(TodoMirror.kb_id == kb.id, TodoMirror.status == "open")
            )
        ).scalar_one()
    )
    todo_done = int(
        (
            await session.execute(
                select(func.count())
                .select_from(TodoMirror)
                .where(TodoMirror.kb_id == kb.id, TodoMirror.status == "done")
            )
        ).scalar_one()
    )
    wiki_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(WikiPage)
                .where(WikiPage.kb_id == kb.id)
            )
        ).scalar_one()
    )

    pinned_expr = Note.props_json.op("->>")("pinned").in_(("true", "True", "1"))
    latest_rows = (
        (
            await session.execute(
                select(Note)
                .where(*active)
                .order_by(Note.created_at.desc())
                .limit(6)
            )
        )
        .scalars()
        .all()
    )
    pinned_rows = (
        (
            await session.execute(
                select(Note)
                .where(*active, pinned_expr)
                .order_by(Note.updated_at.desc())
                .limit(6)
            )
        )
        .scalars()
        .all()
    )

    recent_cutoff = now - timedelta(days=90)
    frequent_rows = (
        await session.execute(
            select(Note, func.count(NoteRevision.id))
            .join(NoteRevision, NoteRevision.note_id == Note.id)
            .where(*active, NoteRevision.created_at >= recent_cutoff)
            .group_by(Note.id)
            .order_by(func.count(NoteRevision.id).desc(), Note.updated_at.desc())
            .limit(6)
        )
    ).all()
    frequent_notes = [row[0] for row in frequent_rows]
    if len(frequent_notes) < 6:
        exclude = [note.id for note in frequent_notes]
        fill_stmt = select(Note).where(*active)
        if exclude:
            fill_stmt = fill_stmt.where(Note.id.notin_(exclude))
        frequent_notes.extend(
            (
                await session.execute(
                    fill_stmt.order_by(Note.updated_at.desc()).limit(
                        6 - len(frequent_notes)
                    )
                )
            )
            .scalars()
            .all()
        )

    def summary(note: Note) -> NoteSummary:
        return NoteSummary.model_validate(note, from_attributes=True)

    return KBDashboardOut(
        kb_id=kb.id,
        kb_name=kb.name,
        description=kb.description or "",
        counts=KBDashboardCounts(
            notes=sum(by_kind.values()),
            archived=archived,
            trash=trash,
            folders=folders,
            tags=tags,
            attachments=attachments,
            words=words,
            by_kind=by_kind,
            wiki=wiki_count,
        ),
        study=KBDashboardStudy(
            due_reviews=due_reviews,
            attempted_topics=len(mastery),
            mastered_topics=mastered,
            mastery_coverage=round(mastered / wiki_count, 3) if wiki_count else 0.0,
            todo_open=todo_open,
            todo_done=todo_done,
        ),
        activity=activity,
        tags=tag_stats,
        latest=[summary(note) for note in latest_rows],
        pinned=[summary(note) for note in pinned_rows],
        frequent=[summary(note) for note in frequent_notes],
        generated_at=now,
    )


@router.get("/{kb_id}/dashboard/activity", response_model=KBDashboardDayOut)
async def kb_dashboard_activity(
    kb_id: uuid.UUID,
    day: date = Query(alias="date"),
    session: AsyncSession = Depends(get_session),
):
    """单日活动明细：热力图 / 日历点击某一天时按需加载。

    口径与总览热力图一致：当天创建笔记 + 自动保存产生的历史版本；
    只返回仍活跃（非归档 / 回收站）的笔记，避免给已删除的内容提供入口。
    """
    kb = await _get_kb(session, kb_id)
    events: dict[uuid.UUID, int] = {}
    revision_rows = (
        await session.execute(
            select(NoteRevision.note_id, func.count())
            .join(Note, Note.id == NoteRevision.note_id)
            .where(
                NoteRevision.kb_id == kb.id,
                Note.status == "active",
                func.date(NoteRevision.created_at) == day,
            )
            .group_by(NoteRevision.note_id)
        )
    ).all()
    for note_id, count in revision_rows:
        events[note_id] = events.get(note_id, 0) + int(count)
    created_ids = (
        (
            await session.execute(
                select(Note.id).where(
                    Note.kb_id == kb.id,
                    Note.status == "active",
                    func.date(Note.created_at) == day,
                )
            )
        )
        .scalars()
        .all()
    )
    for note_id in created_ids:
        events[note_id] = events.get(note_id, 0) + 1
    if not events:
        return KBDashboardDayOut(date=day)

    notes = (
        (await session.execute(select(Note).where(Note.id.in_(list(events)))))
        .scalars()
        .all()
    )
    notes.sort(key=lambda note: (events.get(note.id, 0), note.updated_at), reverse=True)
    limit = 20
    return KBDashboardDayOut(
        date=day,
        total=sum(events.values()),
        note_count=len(notes),
        notes=[
            KBDashboardDayNote(
                note=NoteSummary.model_validate(note, from_attributes=True),
                events=events.get(note.id, 0),
            )
            for note in notes[:limit]
        ],
    )


@router.post("", response_model=KBOut, status_code=201)
async def create_kb(data: KBCreate, session: AsyncSession = Depends(get_session)):
    slug = data.slug or _slugify(data.name)
    # 唯一性
    dup = (
        (await session.execute(select(KnowledgeBase).where(KnowledgeBase.slug == slug)))
        .scalars()
        .first()
    )
    if dup:
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"
    max_sort = (
        await session.execute(
            select(func.max(KnowledgeBase.sort_order)).where(
                KnowledgeBase.deleted_at.is_(None)
            )
        )
    ).scalar_one()
    kb = KnowledgeBase(
        name=data.name,
        slug=slug,
        description=data.description,
        embedding_model=data.embedding_model or settings.embed_model,
        llm_config_id=data.llm_config_id,
        learning_enabled=data.learning_enabled,
        wiki_compile_interval_hours=data.wiki_compile_interval_hours,
        todo_sync_interval_hours=data.todo_sync_interval_hours,
        sort_order=int(max_sort or 0) + 1,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return KBOut.model_validate(kb, from_attributes=True)


@router.post("/import", response_model=KBImportOut, status_code=201)
async def import_kb(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """导入 Kiwi 专用 ``.kiwizip`` 知识库包，始终创建新的知识库。"""
    suffix = Path(file.filename or "").suffix.lower() or ".kiwizip"
    if suffix not in (".kiwizip", ".zip"):
        raise HTTPException(400, "请选择 .kiwizip 格式的知识库导出包")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        size = 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > kb_transfer.MAX_PACKAGE_BYTES:
                raise kb_transfer.TransferError("导出包超过 500MB 上限")
            tmp.write(chunk)
        tmp.close()
        if size == 0:
            raise kb_transfer.TransferError("上传文件为空")
        kb, stats = await kb_transfer.import_package(session, Path(tmp.name))
    except kb_transfer.TransferError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        await file.close()

    await audit.record(
        session,
        "kb.import",
        kb_id=kb.id,
        target_type="kb",
        target_id=kb.id,
        detail={
            "name": kb.name,
            "filename": file.filename,
            "stats": stats.model_dump() if hasattr(stats, "model_dump") else stats,
        },
        note=f"导入知识库包：{kb.name}",
    )
    await session.commit()

    return KBImportOut(
        kb=KBOut.model_validate(kb, from_attributes=True),
        stats=stats,
    )


@router.get("/{kb_id}/export")
async def export_kb(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """导出知识库全量数据（业务表 + 原始素材 + 附件）为 ``.kiwizip``。"""
    kb = await _get_kb(session, kb_id)
    try:
        path, filename = await kb_transfer.build_export(session, kb_id)
    except kb_transfer.TransferError as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit.record(
        session,
        "kb.export",
        kb_id=kb_id,
        target_type="kb",
        target_id=kb_id,
        detail={"name": kb.name, "filename": filename, "size": Path(path).stat().st_size},
        note=f"导出知识库：{kb.name}",
    )
    await session.commit()
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: Path(path).unlink(missing_ok=True)),
    )


@router.get("/builtin", response_model=BuiltinKbStatus)
async def builtin_status(session: AsyncSession = Depends(get_session)):
    """内置演示库状态：隐藏后供前端展示还原入口。"""
    return BuiltinKbStatus(**await get_builtin_status(session))


@router.post("/builtin/restore", response_model=KBOverview)
async def builtin_restore(session: AsyncSession = Depends(get_session)):
    kb = await restore_builtin(session)
    if kb is None:
        raise HTTPException(500, "内置知识库还原失败")
    return await _overview(session, kb)


@router.post("/reorder", status_code=204)
async def reorder_kbs(data: KBReorderIn, session: AsyncSession = Depends(get_session)):
    """知识库卡片排序；要求包含全部可见知识库，避免并发时漏项。"""
    existing = set(
        (
            await session.execute(
                select(KnowledgeBase.id).where(KnowledgeBase.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    incoming = list(data.ordered_ids)
    if len(incoming) != len(set(incoming)):
        raise HTTPException(400, "排序列表包含重复知识库")
    if set(incoming) != existing:
        raise HTTPException(400, "排序列表必须包含全部知识库")
    for index, kb_id in enumerate(incoming):
        await session.execute(
            KnowledgeBase.__table__.update()
            .where(KnowledgeBase.id == kb_id)
            .values(sort_order=index)
        )
    await session.commit()


@router.post("/{kb_id}/todos/sync", response_model=dict)
async def sync_todos(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """立即把知识库内全部待办汇总到收件箱，并把勾选状态同步回来源。"""
    await _get_kb(session, kb_id)
    return await todo_sync.sync_kb_todos(session, kb_id)


@router.get("/{kb_id}/todos/{todo_id}", response_model=dict)
async def get_todo_source(
    kb_id: uuid.UUID,
    todo_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """待办镜像 → 来源笔记：收件箱里的来源标题据此跳转（兼容旧链接）。"""
    await _get_kb(session, kb_id)
    mirror = await session.get(TodoMirror, todo_id)
    if mirror is None or mirror.kb_id != kb_id:
        raise HTTPException(404, "待办不存在")
    # 任务项在正文中的序号（0 起）：前端据此滚动到对应复选框，
    # 不依赖展示文本，避免任务里含有颜色/字号等内联标记时匹配失败。
    task_index = -1
    plugin_location: dict = {}
    if mirror.source_kind in ("task", "plugin_task"):
        source_note = await session.get(Note, mirror.source_note_id)
        if source_note is not None:
            if mirror.source_kind == "task":
                for index, (ref, _text, _checked) in enumerate(
                    todo_sync.task_items(source_note.body_md or "")
                ):
                    if ref == mirror.source_ref:
                        task_index = index
                        break
            else:
                plugin_location = (
                    todo_sync.plugin_task_location(
                        source_note.body_md or "", mirror.source_ref
                    )
                    or {}
                )
    return {
        "id": str(mirror.id),
        "source_note_id": str(mirror.source_note_id),
        "source_kind": mirror.source_kind,
        "source_ref": mirror.source_ref,
        "source_text": mirror.source_text,
        "title": mirror.title,
        "status": mirror.status,
        "task_index": task_index,
        **plugin_location,
    }


@router.get("/{kb_id}", response_model=KBOverview)
async def get_kb(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    kb = await _get_kb(session, kb_id)
    return await _overview(session, kb)


@router.patch("/{kb_id}", response_model=KBOut)
async def update_kb(kb_id: uuid.UUID, data: KBUpdate, session: AsyncSession = Depends(get_session)):
    kb = await _get_kb(session, kb_id)
    if data.name is not None:
        kb.name = data.name
    if data.description is not None:
        kb.description = data.description
    if data.embedding_model is not None:
        kb.embedding_model = data.embedding_model
    if data.pinned is not None:
        kb.pinned = data.pinned
    if data.learning_enabled is not None:
        kb.learning_enabled = data.learning_enabled
    if data.wiki_compile_interval_hours is not None:
        kb.wiki_compile_interval_hours = data.wiki_compile_interval_hours
    if data.todo_sync_interval_hours is not None:
        kb.todo_sync_interval_hours = data.todo_sync_interval_hours
    # 用 model_fields_set 而非 is not None：支持显式传 null 来清空绑定（回落全局默认）
    if "llm_config_id" in data.model_fields_set:
        kb.llm_config_id = data.llm_config_id
    await session.commit()
    await session.refresh(kb)
    return KBOut.model_validate(kb, from_attributes=True)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    kb = await _get_kb(session, kb_id)
    if kb.is_builtin:
        # 内置演示库同样硬删除：数据 / 素材 / 向量全部清理，
        # 之后可在知识库页按当前随包内容重新创建。
        await purge_builtin_kb(session, kb)
        await audit.record(
            session,
            "kb.delete",
            kb_id=kb_id,
            target_type="kb",
            target_id=kb_id,
            detail={"name": kb.name, "builtin": True},
            note=f"删除内置知识库：{kb.name}",
        )
        await session.commit()
        return
    # 级联删除库内数据，向量兜底清理
    if not is_disabled():
        try:
            qdrant_store.purge_kb(kb_id)
        except Exception:  # noqa: BLE001
            pass
    kernel_manager.purge_kb(str(kb_id))
    forget_kb(kb_id)
    await session.delete(kb)
    await audit.record(
        session,
        "kb.delete",
        kb_id=kb_id,
        target_type="kb",
        target_id=kb_id,
        detail={"name": kb.name, "builtin": False},
        note=f"删除知识库：{kb.name}",
    )
    await session.commit()
