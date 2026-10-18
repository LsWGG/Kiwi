"""Repository 层：所有数据访问强制 kb_id 边界。

设计要点：
- 每个带 kb 边界的实体一个 repo。
- 所有方法首参 kb_id，update/delete 在 SQL 侧强制 and_(kb_id, id)，0 行命中抛权限错误。
- 无独立 kb 列的关联表通过父实体保证边界。
"""

import contextvars
import uuid

from sqlalchemy import and_, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class KBPermissionError(Exception):
    """知识库边界被跨越。"""


# 当前 kb contextvar（由中间件注入 X-KB-Id）
current_kb: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_kb", default=None
)


def require_kb(kb_id: uuid.UUID | None) -> uuid.UUID:
    """从 contextvar 取当前 kb；显式传入优先。"""
    if kb_id is not None:
        return kb_id
    cur = current_kb.get()
    if cur is None:
        raise KBPermissionError("no kb_id provided and no X-KB-Id header set")
    return cur


class BaseRepo:
    """泛型 base repo，entity 必须含 kb_id 列。"""

    entity: type[Base]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, kb_id: uuid.UUID, obj_id: uuid.UUID):
        """取单个，校验归属。"""
        row = await self.session.get(self.entity, obj_id)
        if row is None or getattr(row, "kb_id", None) != kb_id:
            raise KBPermissionError(f"{self.entity.__name__} {obj_id} not in kb {kb_id}")
        return row

    async def list(self, kb_id: uuid.UUID, **filters):
        """列表，强制 kb 过滤 + 可选过滤条件。"""
        from sqlalchemy import select

        stmt = select(self.entity).where(self.entity.kb_id == kb_id)
        for k, v in filters.items():
            if v is not None and hasattr(self.entity, k):
                stmt = stmt.where(getattr(self.entity, k) == v)
        stmt = stmt.order_by(self.entity.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, kb_id: uuid.UUID, **values):
        obj = self.entity(kb_id=kb_id, **values)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update(self, kb_id: uuid.UUID, obj_id: uuid.UUID, **values):
        """按 kb_id+id 强制更新，0 行抛权限错误。"""
        values = {k: v for k, v in values.items() if v is not None}
        if not values:
            return await self.get(kb_id, obj_id)
        stmt = (
            update(self.entity)
            .where(and_(self.entity.kb_id == kb_id, self.entity.id == obj_id))
            .values(**values)
        )
        res = await self.session.execute(stmt)
        if res.rowcount == 0:
            raise KBPermissionError(f"{self.entity.__name__} {obj_id} not in kb {kb_id}")
        await self.session.flush()
        return await self.get(kb_id, obj_id)

    async def delete(self, kb_id: uuid.UUID, obj_id: uuid.UUID) -> None:
        stmt = delete(self.entity).where(and_(self.entity.kb_id == kb_id, self.entity.id == obj_id))
        res = await self.session.execute(stmt)
        if res.rowcount == 0:
            raise KBPermissionError(f"{self.entity.__name__} {obj_id} not in kb {kb_id}")
        await self.session.flush()
