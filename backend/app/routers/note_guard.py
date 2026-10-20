"""笔记密码锁的通用 FastAPI 依赖。

数据表 / Notebook 等专用路由不经过 ``notes`` 路由的序列化函数，直接在路由级
挂载该依赖，保证上锁笔记的结构化内容（行数据、Notebook 单元格、导出文件）
不会从旁路读取。
"""

import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note
from app.db.session import get_session
from app.services import note_lock


async def require_unlocked_note(
    note_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
) -> None:
    """路径里带 note_id 且该笔记已上锁时，要求有效的解锁令牌。

    没有 note_id 的路由（如 Notebook 导入）直接放行；笔记不存在或不属于
    该知识库时交给具体路由返回 404，保持原有错误语义。
    """
    if note_id is None or kb_id is None:
        return
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id:
        return
    if note.is_locked and not note_lock.token_is_valid(note, x_note_token):
        raise HTTPException(403, "笔记已上锁，请先输入密码解锁后再操作")
