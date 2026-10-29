"""问答会话路由：历史记录持久化、重命名、删除与清空。

会话独立于知识库（检索范围可跨库），消息以 JSONB 保存，包含引用信息，
因此刷新页面、重启服务后仍可查看完整历史并继续追问。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession
from app.db.session import get_session
from app.schemas.chat_session import (
    ChatSessionCreate,
    ChatSessionList,
    ChatSessionOut,
    ChatSessionSummary,
    ChatSessionUpdate,
)

router = APIRouter(prefix="/api/chat/sessions", tags=["chat-sessions"])

MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 50_000


def _clean_messages(raw: list[dict] | None) -> list[dict]:
    """只保留 user / assistant 消息，裁剪异常长度，防止 JSONB 无限膨胀。"""
    out: list[dict] = []
    for item in (raw or [])[-MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = str(item.get("content") or "")[:MAX_MESSAGE_CHARS]
        citations = item.get("citations")
        if not isinstance(citations, list):
            citations = []
        created_at = item.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        out.append(
            {
                "role": role,
                "content": content,
                "citations": citations,
                "created_at": created_at,
            }
        )
    return out


def _auto_title(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            text = " ".join(str(message["content"]).split())
            return text[:40] or "新对话"
    return "新对话"


def _summary(session: ChatSession) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        message_count=session.message_count,
        scope=session.scope_json or {},
        intent=session.intent,
        llm_config_id=session.llm_config_id,
        last_message_at=session.last_message_at,
        updated_at=session.updated_at,
    )


def _detail(session: ChatSession) -> ChatSessionOut:
    return ChatSessionOut(
        **_summary(session).model_dump(),
        messages=session.messages_json or [],
    )


async def _get_session(
    db: AsyncSession, session_id: uuid.UUID
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(404, "会话不存在")
    return session


def _kb_scope_filter(kb_id: uuid.UUID):
    """会话按知识库隔离：属于该库，或检索范围为全局（所有库）。

    ``scope_json`` 是 JSONB：global 的会话在每个库下都可见；kb / multi 的
    会话凭 ``kb_ids`` 数组归属。没有 kb 参数的调用保持旧行为（返回全部）。
    """
    return or_(
        ChatSession.scope_json["scope"].astext == "global",
        ChatSession.scope_json.contains({"kb_ids": [str(kb_id)]}),
    )


@router.get("", response_model=ChatSessionList)
async def list_sessions(
    limit: int = Query(100, ge=1, le=500),
    kb_id: uuid.UUID | None = Query(None, description="只看该知识库的会话"),
    session: AsyncSession = Depends(get_session),
):
    """按最近消息时间倒序列出会话（不含消息正文）。"""
    stmt = select(ChatSession)
    if kb_id is not None:
        stmt = stmt.where(_kb_scope_filter(kb_id))
    rows = (
        (
            await session.execute(
                stmt.order_by(
                    func.coalesce(
                        ChatSession.last_message_at, ChatSession.updated_at
                    ).desc()
                ).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ChatSessionList(items=[_summary(item) for item in rows])


@router.post("", response_model=ChatSessionOut, status_code=201)
async def create_session(
    data: ChatSessionCreate, session: AsyncSession = Depends(get_session)
):
    messages = _clean_messages(data.messages)
    title = (data.title or "").strip()[:200] or _auto_title(messages)
    item = ChatSession(
        title=title,
        scope_json=data.scope or {},
        intent=(data.intent or "auto").strip() or "auto",
        llm_config_id=data.llm_config_id,
        messages_json=messages,
        message_count=len(messages),
        last_message_at=datetime.now(timezone.utc) if messages else None,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _detail(item)


@router.get("/{session_id}", response_model=ChatSessionOut)
async def get_session_detail(
    session_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    return _detail(await _get_session(session, session_id))


@router.patch("/{session_id}", response_model=ChatSessionOut)
async def update_session(
    session_id: uuid.UUID,
    data: ChatSessionUpdate,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_session(session, session_id)
    fields = data.model_fields_set

    messages: list[dict] | None = None
    if "messages" in fields and data.messages is not None:
        messages = _clean_messages(data.messages)
        item.messages_json = messages
        item.message_count = len(messages)
        item.last_message_at = datetime.now(timezone.utc) if messages else None

    if data.title is not None:
        title = data.title.strip()[:200]
        if title:
            item.title = title
    elif messages is not None and item.title in ("", "新对话"):
        item.title = _auto_title(messages)

    if data.scope is not None:
        item.scope_json = data.scope
    if data.intent is not None:
        intent = data.intent.strip() or "auto"
        if intent not in ("auto", "wiki", "note", "raw"):
            raise HTTPException(400, "无效的检索意图")
        item.intent = "note" if intent == "raw" else intent
    if data.clear_llm_config:
        item.llm_config_id = None
    elif "llm_config_id" in fields:
        item.llm_config_id = data.llm_config_id

    await session.commit()
    await session.refresh(item)
    return _detail(item)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    item = await _get_session(session, session_id)
    await session.delete(item)
    await session.commit()


@router.delete("", response_model=dict)
async def clear_sessions(
    kb_id: uuid.UUID | None = Query(None, description="只清空该知识库的会话"),
    session: AsyncSession = Depends(get_session),
):
    """清空会话历史；指定 kb_id 时只删该库可见的会话。"""
    stmt = delete(ChatSession)
    if kb_id is not None:
        stmt = stmt.where(_kb_scope_filter(kb_id))
    result = await session.execute(stmt)
    await session.commit()
    return {"deleted": result.rowcount or 0}
