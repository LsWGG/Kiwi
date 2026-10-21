"""笔记密码锁与正文加密。"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    KnowledgeBase,
    NoteRevision,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _get_note,
    _require_unlocked,
)
from app.schemas.note import (
    NoteLockIn,
    NoteLockOut,
    NoteLockRemoveIn,
    NoteUnlockIn,
)
from app.services import (
    note_lock,
    qdrant_store,
)

logger = logging.getLogger("kiwi.notes.lock")

router = APIRouter()

# ---- 密码锁 ----

@router.post("/{note_id}/lock", response_model=NoteLockOut)
async def set_note_lock(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteLockIn,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """给笔记设置密码；已上锁时需先持有当前解锁令牌。

    ``encrypt=true`` 时把正文转为密码派生的 Fernet 密文；历史版本中的明文
    会一并删除，避免从版本记录绕过加密。密码丢失不可恢复。
    """
    note = await _get_note(session, kb_id, note_id)
    _require_unlocked(note, x_note_token, "修改密码")
    salt = note_lock.new_salt()
    content_key: bytes | None = None
    try:
        if note_lock.is_encrypted(note):
            old_key = note_lock.token_content_key(note, x_note_token)
            if old_key is None:
                raise note_lock.NoteEncryptionError("请先解锁后再修改加密笔记")
            plaintext = note_lock.decrypt_with_key(old_key, note.body_enc or "")
        else:
            plaintext = note.body_md or ""
        if data.encrypt:
            enc_salt = note_lock.new_salt()
            note.body_enc = note_lock.encrypt_body(data.password, enc_salt, plaintext)
            note.body_md = ""
            note.lock_encrypted = True
            note.lock_enc_salt = enc_salt
            content_key = note_lock.derive_content_key(data.password, enc_salt)
            # 历史版本是明文，启用加密时清除。
            await session.execute(delete(NoteRevision).where(NoteRevision.note_id == note.id))
        else:
            # 从加密回到普通锁：保留正文，仅移除密文。
            note.body_md = plaintext
            note.body_enc = None
            note.lock_encrypted = False
            note.lock_enc_salt = None
    except note_lock.NoteEncryptionError as e:
        raise HTTPException(400, str(e)) from e
    note.lock_salt = salt
    note.lock_hash = note_lock.hash_password(data.password, salt)
    note.lock_hint = (data.hint or "").strip()[:120] or None
    note.locked_at = datetime.now(timezone.utc)
    token, expires_at = note_lock.issue_unlock_token(note, content_key=content_key)
    await session.commit()
    # 上锁后立即清理该笔记的问答向量，避免正文从 AI 检索侧泄露。
    try:
        kb = await session.get(KnowledgeBase, kb_id)
        if kb is not None:
            await asyncio.to_thread(qdrant_store.delete_note_chunks, note.id, kb.embedding_model)
    except Exception:  # noqa: BLE001 —— 向量库不可用时由后台巡检兜底
        logger.warning("清理上锁笔记向量失败：%s", note.id, exc_info=True)
    return NoteLockOut(
        token=token,
        expires_at=expires_at,
        is_locked=True,
        encrypted=bool(content_key),
    )


@router.post("/{note_id}/unlock", response_model=NoteLockOut)
async def unlock_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteUnlockIn,
    session: AsyncSession = Depends(get_session),
):
    """校验密码并签发 2 小时有效的解锁令牌。"""
    note = await _get_note(session, kb_id, note_id)
    if not note.is_locked:
        return NoteLockOut(token="", expires_at=0, is_locked=False)
    if not note_lock.verify_password(note, data.password):
        raise HTTPException(401, "密码不正确")
    content_key = None
    if note_lock.is_encrypted(note) and note.lock_enc_salt:
        content_key = note_lock.derive_content_key(data.password, note.lock_enc_salt)
    try:
        token, expires_at = note_lock.issue_unlock_token(note, content_key=content_key)
    except note_lock.NoteEncryptionError as e:
        raise HTTPException(500, str(e)) from e
    return NoteLockOut(
        token=token,
        expires_at=expires_at,
        is_locked=True,
        encrypted=bool(content_key),
    )


@router.delete("/{note_id}/lock", status_code=204)
async def remove_note_lock(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteLockRemoveIn | None = Body(default=None),
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """移除密码锁：需要密码或有效解锁令牌；加密正文会先解密回明文。"""
    note = await _get_note(session, kb_id, note_id)
    password_ok = bool(
        data and data.password and note_lock.verify_password(note, data.password)
    )
    if note.is_locked and not password_ok and not note_lock.token_is_valid(note, x_note_token):
        raise HTTPException(403, "请输入密码或先解锁后再移除密码")
    if note_lock.is_encrypted(note):
        try:
            if password_ok and note.lock_enc_salt:
                plaintext = note_lock.decrypt_body(
                    data.password or "", note.lock_enc_salt, note.body_enc or ""
                )
            else:
                key = note_lock.token_content_key(note, x_note_token)
                if key is None:
                    raise note_lock.NoteEncryptionError("无法取得解密密钥，请重新解锁")
                plaintext = note_lock.decrypt_with_key(key, note.body_enc or "")
        except note_lock.NoteEncryptionError as e:
            raise HTTPException(400, str(e)) from e
        note.body_md = plaintext
        note.body_enc = None
        note.lock_encrypted = False
        note.lock_enc_salt = None
    note.lock_hash = None
    note.lock_salt = None
    note.lock_hint = None
    note.locked_at = None
    await session.commit()


