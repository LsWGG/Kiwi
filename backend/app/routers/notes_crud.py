"""笔记读取、创建、更新与反向链接。"""

import logging
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CollectionRow,
    Note,
    NoteCollection,
    NoteLink,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _get_note,
    _move_subtree_folder,
    _next_note_sort,
    _rebuild_links,
    _reload_tags,
    _require_unlocked,
    _serialize_note,
    _snapshot_revision,
    _sync_note_tags,
    _validate_folder,
    _validate_note_parent,
)
from app.schemas.note import (
    NoteBacklinkOut,
    NoteCreate,
    NoteOut,
    NoteUpdate,
)
from app.services import (
    note_lock,
    todo_sync,
)
from app.services.note_database import (
    ensure_collection,
)

logger = logging.getLogger("kiwi.notes.crud")

router = APIRouter()

@router.get("/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    include_trash: bool = False,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id, include_trash=include_trash)
    return _serialize_note(note, x_note_token)


def _link_context(body: str, title: str, note_id: uuid.UUID | None = None, span: int = 60) -> str:
    """提取引用处前后文，供反向链接面板展示。

    优先定位指向当前笔记的 @ 提及（按 id，标题可能已改），再回退到
    ``[[标题]]`` 与任意链接语法。
    """
    match = None
    if note_id is not None:
        match = re.search(
            rf"\[@[^\]]*\]\(kiwi://note/{re.escape(str(note_id))}(?:\?[^)]*)?\)",
            body,
        )
    if match is None:
        needle = f"[[{title}]]"
        idx = body.find(needle)
        if idx >= 0:
            start = max(0, idx - span)
            end = min(len(body), idx + len(needle) + span)
            snippet = body[start:end].replace("\n", " ").strip()
            return ("…" if start > 0 else "") + snippet + ("…" if end < len(body) else "")
    if match is None:
        match = re.search(r"\[\[[^\]]+\]\]|\[@[^\]]*\]\(kiwi://(?:note|wiki)/[^)]+\)", body)
    if match is None:
        return body.strip().replace("\n", " ")[: span * 2]
    start = max(0, match.start() - span)
    end = min(len(body), match.end() + span)
    snippet = body[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(body) else "")


@router.get("/{note_id}/backlinks", response_model=list[NoteBacklinkOut])
async def backlinks(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """反向链接：引用当前笔记的其他笔记（附引用上下文）。"""
    target = await _get_note(session, kb_id, note_id)
    in_links = (
        (await session.execute(select(NoteLink).where(NoteLink.to_note_id == note_id)))
        .scalars()
        .all()
    )
    ids = [link.from_note_id for link in in_links]
    if not ids:
        return []
    rows = (
        (
            await session.execute(
                select(Note).where(
                    Note.id.in_(ids),
                    Note.kb_id == kb_id,
                    # 上锁笔记的正文片段不能出现在反向链接上下文里。
                    Note.lock_hash.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    items: list[NoteBacklinkOut] = []
    for note in rows:
        item = NoteBacklinkOut.model_validate(note, from_attributes=True)
        item.context = _link_context(note.body_md or "", target.title, target.id)
        items.append(item)
    return items


def _default_notebook_doc() -> dict:
    """新建 Notebook 的初始内容（与前端 emptyNotebook 保持一致）。"""
    return {
        "version": 1,
        "language": "python",
        "cells": [
            {
                "id": "cell-intro",
                "type": "markdown",
                "source": (
                    "## 未命名 Notebook\n\n"
                    "在这里记录分析思路，代码单元格中可以直接使用 `pandas`、`numpy`、"
                    "`matplotlib` 等项目依赖。\n\n"
                    "- 需要新依赖：`%pip install 包名` 或 `%uv pip install 包名`（沙箱已开启网络）\n"
                    "- 执行 shell：`!ls`、`!pwd`；整段脚本可用 `%%bash`\n"
                    "- 快捷键：`Shift+Enter` 运行并跳转，`Ctrl+Enter` 运行并停留，"
                    "`Alt+Enter` 运行并插入"
                ),
            },
            {
                "id": "cell-hello",
                "type": "code",
                "source": "print('Hello, Kiwi!')",
                "execution_count": None,
                "outputs": [],
            },
        ],
    }


@router.post("", response_model=NoteOut, status_code=201)
async def create_note(
    data: NoteCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _validate_folder(session, kb_id, data.folder_id)
    parent = await _validate_note_parent(
        session, kb_id, None, data.parent_note_id
    )
    # 子笔记与父笔记处于同一分组，客户端传入的分组不参与定位。
    folder_id = parent.folder_id if parent is not None else data.folder_id
    sort_order = data.sort_order
    if sort_order is None:
        sort_order = await _next_note_sort(
            session, kb_id, folder_id, data.parent_note_id
        )
    note = Note(
        kb_id=kb_id,
        title=data.title.strip(),
        body_md=data.body_md,
        kind=data.kind,
        folder_id=folder_id,
        parent_note_id=data.parent_note_id,
        source_id=data.source_id,
        status="active",
        view_mode=data.view_mode,
        sort_order=sort_order,
        props_json=data.props_json or {},
    )
    session.add(note)
    await session.flush()
    if note.kind == "database":
        await ensure_collection(session, note)
    elif note.kind == "notebook":
        props = dict(note.props_json or {})
        props.setdefault("notebook_doc", _default_notebook_doc())
        note.props_json = props
    if data.tags:
        await _sync_note_tags(session, note, data.tags)
    await _rebuild_links(session, kb_id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteUpdate,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    _require_unlocked(note, x_note_token, "编辑")
    # 内容发生变化时先记录变更前的快照，供历史记录查看与还原。
    incoming_title = (
        data.title
        if "title" in data.model_fields_set and data.title is not None
        else note.title
    )
    incoming_body = (
        data.body_md
        if "body_md" in data.model_fields_set and data.body_md is not None
        else note.body_md
    )
    if incoming_title != note.title or incoming_body != note.body_md:
        await _snapshot_revision(session, note, source="auto")
    location_changed = False
    if "parent_note_id" in data.model_fields_set:
        parent = await _validate_note_parent(
            session, kb_id, note.id, data.parent_note_id
        )
        new_folder_id = (
            parent.folder_id
            if parent is not None
            else (
                data.folder_id
                if "folder_id" in data.model_fields_set
                else note.folder_id
            )
        )
        if parent is None and "folder_id" in data.model_fields_set:
            await _validate_folder(session, kb_id, new_folder_id)
        if (
            data.parent_note_id != note.parent_note_id
            or new_folder_id != note.folder_id
        ):
            note.parent_note_id = data.parent_note_id
            note.folder_id = new_folder_id
            location_changed = True
    elif "folder_id" in data.model_fields_set:
        await _validate_folder(session, kb_id, data.folder_id)
        if note.folder_id != data.folder_id:
            note.folder_id = data.folder_id
            # 子笔记不能跨分组挂在父笔记下；换组即提升为该组根级笔记。
            if note.parent_note_id is not None:
                note.parent_note_id = None
            location_changed = True
    if location_changed:
        if "sort_order" not in data.model_fields_set or data.sort_order is None:
            note.sort_order = await _next_note_sort(
                session, kb_id, note.folder_id, note.parent_note_id
            )
        await _move_subtree_folder(session, kb_id, note.id, note.folder_id)
    for field in ("title", "body_md", "status", "view_mode", "sort_order"):
        if field in data.model_fields_set:
            val = getattr(data, field)
            if val is not None:
                setattr(note, field, val)
    encrypted_body_key: bytes | None = None
    if data.body_md is not None and note_lock.is_encrypted(note):
        # 更新流程先用明文重建双链 / 待办，写库前再加密并清空 body_md。
        encrypted_body_key = note_lock.token_content_key(note, x_note_token)
        if encrypted_body_key is None:
            raise HTTPException(403, "笔记已加密，请重新解锁后再编辑")
    if data.props_json is not None:
        # JSONB 需整体赋值；顶层合并保留导入状态等服务端字段
        note.props_json = {**(note.props_json or {}), **data.props_json}
    if data.tags is not None:
        await _sync_note_tags(session, note, data.tags)
    if data.body_md is not None or data.title is not None:
        await _rebuild_links(session, kb_id, note)
    if note.kind == "database" and data.title is not None:
        coll = (
            await session.execute(
                select(NoteCollection).where(NoteCollection.note_id == note.id)
            )
        ).scalar_one_or_none()
        if coll is not None:
            coll.name = note.title
    if data.title is not None:
        # 行笔记标题即集合的标题字段：改名写回行数据，避免下次加载被覆盖
        row_id = (note.props_json or {}).get("collection_row_id")
        if row_id:
            try:
                row = await session.get(CollectionRow, uuid.UUID(str(row_id)))
            except (ValueError, TypeError):
                row = None
            if row is not None and row.note_id == note.id:
                coll = (
                    await session.execute(
                        select(NoteCollection).where(NoteCollection.id == row.collection_id)
                    )
                ).scalar_one_or_none()
                fields = (coll.schema_json or {}).get("fields") or [] if coll else []
                title_field = next(
                    (f["id"] for f in fields if f["id"] in ("name", "title")), None
                ) or next(
                    (
                        f["id"]
                        for f in fields
                        if f.get("type") in ("text", "long_text", "url")
                    ),
                    None,
                )
                if title_field:
                    row.data = {**(row.data or {}), title_field: note.title}
    is_todo_hub = bool((note.props_json or {}).get("todo_hub"))
    if data.body_md is not None:
        if is_todo_hub:
            # 收件箱勾选 → 写回来源笔记 / 数据表
            await todo_sync.apply_hub_checks(session, note)
        else:
            # 来源笔记变化 → 稍后刷新收件箱（合并自动保存的连续写入）
            todo_sync.schedule_kb_sync(kb_id)
    if encrypted_body_key is not None:
        note.body_enc = note_lock.encrypt_with_key(encrypted_body_key, note.body_md or "")
        note.body_md = ""
    await session.commit()
    if is_todo_hub:
        todo_sync.schedule_kb_sync(kb_id, delay=2.5)
    await _reload_tags(session, note)
    return _serialize_note(note, x_note_token)


