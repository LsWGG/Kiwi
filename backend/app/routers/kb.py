"""知识库路由。"""

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase, Note, Source, StudyProfile, StudyReview, WikiPage
from app.db.session import get_session
from app.schemas.kb import BuiltinKbStatus, KBCreate, KBOut, KBOverview, KBUpdate
from app.services import qdrant_store
from app.services.builtin_demo import (
    get_builtin_status,
    purge_builtin_kb,
    restore_builtin,
)
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
                .order_by(KnowledgeBase.pinned.desc(), KnowledgeBase.created_at.desc())
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
        last_activity_at=last_activity,
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
    kb = KnowledgeBase(
        name=data.name,
        slug=slug,
        description=data.description,
        embedding_model=data.embedding_model or settings.embed_model,
        llm_config_id=data.llm_config_id,
        learning_enabled=data.learning_enabled,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return KBOut.model_validate(kb, from_attributes=True)


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
        await session.commit()
        return
    # 级联删除库内数据，向量兜底清理
    try:
        qdrant_store.purge_kb(kb_id)
    except Exception:  # noqa: BLE001
        pass
    kernel_manager.purge_kb(str(kb_id))
    forget_kb(kb_id)
    await session.delete(kb)
    await session.commit()
