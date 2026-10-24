"""只读分享链接的管理接口（需登录 / 访问令牌）。"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import NoteShare
from app.db.session import get_session
from app.routers.notes_shared import _get_note
from app.schemas.note import NoteShareCreate, NoteShareOut
from app.services import note_lock

router = APIRouter()

MAX_ACTIVE_SHARES = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_active(share: NoteShare) -> bool:
    return share.revoked_at is None and share.expires_at > _now()


def _serialize(share: NoteShare) -> NoteShareOut:
    path = f"/share/{share.token}"
    base_url = settings.public_base_url.strip().rstrip("/")
    return NoteShareOut(
        id=share.id,
        note_id=share.note_id,
        token=share.token,
        path=path,
        url=f"{base_url}{path}" if base_url else None,
        expires_at=share.expires_at,
        has_password=share.has_password,
        view_count=share.view_count,
        last_viewed_at=share.last_viewed_at,
        revoked_at=share.revoked_at,
        created_at=share.created_at,
        active=_is_active(share),
    )


@router.get("/{note_id}/shares", response_model=list[NoteShareOut])
async def list_shares(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """当前笔记仍有效的分享链接（按创建时间倒序）。"""
    await _get_note(session, kb_id, note_id)
    shares = (
        (
            await session.execute(
                select(NoteShare)
                .where(
                    NoteShare.note_id == note_id,
                    NoteShare.kb_id == kb_id,
                    NoteShare.revoked_at.is_(None),
                    NoteShare.expires_at > _now(),
                )
                .order_by(NoteShare.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize(share) for share in shares]


@router.post("/{note_id}/shares", response_model=NoteShareOut, status_code=201)
async def create_share(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteShareCreate,
    session: AsyncSession = Depends(get_session),
):
    """创建只读分享链接。

    上锁笔记（含加密存储）必须先移除密码锁：分享页无法携带解锁令牌，
    否则会绕过笔记锁直接暴露正文。
    """
    note = await _get_note(session, kb_id, note_id)
    if note.is_locked:
        raise HTTPException(400, "上锁笔记不支持创建分享链接，请先移除密码锁")

    active_count = (
        await session.execute(
            select(func.count(NoteShare.id)).where(
                NoteShare.note_id == note_id,
                NoteShare.revoked_at.is_(None),
                NoteShare.expires_at > _now(),
            )
        )
    ).scalar_one()
    if active_count >= MAX_ACTIVE_SHARES:
        raise HTTPException(400, f"单篇笔记最多同时保留 {MAX_ACTIVE_SHARES} 个分享链接")

    password_hash = None
    password_salt = None
    if data.password:
        password_salt = note_lock.new_salt()
        password_hash = note_lock.hash_password(data.password, password_salt)

    share = NoteShare(
        kb_id=kb_id,
        note_id=note_id,
        token=secrets.token_urlsafe(32),
        password_hash=password_hash,
        password_salt=password_salt,
        expires_at=_now() + timedelta(hours=data.expires_in_hours),
    )
    session.add(share)
    await session.commit()
    await session.refresh(share)
    return _serialize(share)


@router.delete("/{note_id}/shares/{share_id}", status_code=204)
async def revoke_share(
    note_id: uuid.UUID,
    share_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """撤销分享链接：立即失效，历史记录保留用于审计。"""
    await _get_note(session, kb_id, note_id, include_trash=True)
    share = await session.get(NoteShare, share_id)
    if share is None or share.note_id != note_id or share.kb_id != kb_id:
        raise HTTPException(404, "分享链接不存在")
    if share.revoked_at is None:
        share.revoked_at = _now()
        await session.commit()
    return Response(status_code=204)
