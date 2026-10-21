"""笔记路由聚合入口。

按路径优先级 include 各子路由：静态路径必须先于 ``/{note_id}`` 注册。
"""

from fastapi import APIRouter

from app.routers import (
    notes_actions,
    notes_compile,
    notes_crud,
    notes_imports,
    notes_lifecycle,
    notes_lock,
    notes_revisions,
    notes_search,
    notes_tags,
    notes_templates,
    notes_tree,
)

router = APIRouter()

for module in (
    notes_tree,
    notes_imports,
    notes_tags,
    notes_templates,
    notes_search,
    notes_lifecycle,
    notes_crud,
    notes_lock,
    notes_revisions,
    notes_compile,
    notes_actions,
):
    router.include_router(module.router, prefix="/api/notes", tags=["notes"])
