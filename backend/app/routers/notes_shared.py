"""笔记路由共享常量与辅助函数。"""

import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CollectionRow,
    Note,
    NoteCollection,
    NoteFolder,
    NoteLink,
    NoteRevision,
    NoteTag,
    NoteTagLink,
    NoteTreeTombstone,
    WikiPage,
)
from app.schemas.note import (
    NoteOut,
)
from app.services import (
    note_lock,
)
from app.services.wiki_links import strip_code

LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
# 编辑器里的 @ 提及持久化为 `[@标题](kiwi://note/<id>)`（可带 display / height 参数）。
# 反向链接、相关笔记和笔记图谱都应把它当作真实入链，而不是只认旧的 [[标题]]。
NOTE_MENTION_RE = re.compile(r"\]\(kiwi://note/([0-9a-fA-F-]{36})(?:\?[^)]*)?\)")
WIKI_MENTION_RE = re.compile(r"\]\(kiwi://wiki/([0-9a-fA-F-]{36})(?:\?[^)]*)?\)")
TRASH_RETENTION_DAYS = 30
# 目录树删除墓碑保留天数：客户端超过该时长未刷新时需做一次全量同步。
TREE_TOMBSTONE_RETENTION_DAYS = 7
# 自动历史版本：2 分钟内的连续编辑合并为一个检查点。
REVISION_COALESCE_SECONDS = 120
# 与前端「历史版本」面板展示的上限保持一致：每篇笔记最多保留 60 个。
REVISION_MAX_PER_NOTE = 60


logger = logging.getLogger("kiwi.notes")

async def _get_note(
    session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID, *, include_trash: bool = False
) -> Note:
    note = (
        await session.execute(
            select(Note).options(selectinload(Note.tags)).where(Note.id == note_id)
        )
    ).scalar_one_or_none()
    if note is None or note.kb_id != kb_id:
        raise HTTPException(404, "笔记不存在")
    if note.status == "trash" and not include_trash:
        raise HTTPException(404, "笔记已在回收站")
    return note


def _serialize_note(note: Note, token: str | None = None) -> NoteOut:
    """序列化笔记；上锁且未解锁时清空正文与结构化内容。

    正文之外的画布 / Notebook 文档、段落格式等都存放在 props_json，
    同样属于笔记内容，未解锁时一并清空，避免从属性侧旁路读取。
    """
    out = NoteOut.model_validate(note, from_attributes=True)
    out.encrypted = note_lock.is_encrypted(note)
    if note.is_locked:
        if note_lock.token_is_valid(note, token):
            out.unlocked = True
            out.body_md = note_lock.note_body(note, token)
        else:
            out.body_md = ""
            out.props_json = {}
    elif out.encrypted:
        # 理论上不可达：加密标记只会与密码锁同时存在。
        out.body_md = note_lock.note_body(note, token)
    return out


def _require_unlocked(note: Note, token: str | None, action: str = "查看") -> None:
    """上锁笔记的内容类操作：无有效令牌时拒绝。"""
    if note.is_locked and not note_lock.token_is_valid(note, token):
        raise HTTPException(403, f"笔记已上锁，请先输入密码解锁后再{action}")


async def _reload_tags(session: AsyncSession, note: Note) -> None:
    """重载标量字段并注入最新标签名（不触发异步关系懒加载）。"""
    await session.refresh(note)
    names = (
        (
            await session.execute(
                select(NoteTag.name)
                .join(NoteTagLink, NoteTagLink.tag_id == NoteTag.id)
                .where(NoteTagLink.note_id == note.id)
                .order_by(NoteTag.name)
            )
        )
        .scalars()
        .all()
    )
    note.__dict__["_tag_names_override"] = list(names)


async def _snapshot_revision(
    session: AsyncSession, note: Note, *, source: str = "auto", coalesce: bool = True
) -> NoteRevision | None:
    """把笔记当前内容写入历史版本。

    自动快照在两分钟内合并：同一个检查点内连续编辑只保留进入编辑前的状态，
    避免自动保存产生大量碎片版本。手动 / 还原快照不合并。

    加密存储的笔记不写历史版本：历史表是明文，会绕过静态加密。
    """
    if note_lock.is_encrypted(note):
        return None
    if coalesce:
        last = (
            await session.execute(
                select(NoteRevision)
                .where(
                    NoteRevision.note_id == note.id,
                    NoteRevision.source.in_(("auto", "manual")),
                )
                .order_by(NoteRevision.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last is not None:
            created = last.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - created).total_seconds()
            if age < REVISION_COALESCE_SECONDS:
                return None

    revision = NoteRevision(
        kb_id=note.kb_id,
        note_id=note.id,
        title=note.title,
        body_md=note.body_md,
        props_json=deepcopy(note.props_json or {}),
        source=source,
    )
    session.add(revision)
    await session.flush()

    stale_ids = (
        (
            await session.execute(
                select(NoteRevision.id)
                .where(NoteRevision.note_id == note.id)
                .order_by(NoteRevision.created_at.desc())
                .offset(REVISION_MAX_PER_NOTE)
            )
        )
        .scalars()
        .all()
    )
    if stale_ids:
        await session.execute(delete(NoteRevision).where(NoteRevision.id.in_(stale_ids)))
    return revision


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lifecycle(note: Note) -> dict:
    return dict((note.props_json or {}).get("lifecycle") or {})


def _set_lifecycle(note: Note, **changes) -> None:
    props = dict(note.props_json or {})
    lifecycle = dict(props.get("lifecycle") or {})
    for key, value in changes.items():
        if value is None:
            lifecycle.pop(key, None)
        else:
            lifecycle[key] = value
    props["lifecycle"] = lifecycle
    note.props_json = props


async def _collection_child_notes(session: AsyncSession, note: Note) -> list[Note]:
    """数据表笔记的所有行笔记（不含数据表自身）。"""
    if note.kind != "database":
        return []
    coll = (
        await session.execute(
            select(NoteCollection).where(NoteCollection.note_id == note.id)
        )
    ).scalar_one_or_none()
    if coll is None:
        return []
    child_ids = select(CollectionRow.note_id).where(
        CollectionRow.collection_id == coll.id,
        CollectionRow.note_id.is_not(None),
        CollectionRow.note_id != note.id,
    )
    return list(
        (await session.execute(select(Note).where(Note.id.in_(child_ids)))).scalars()
    )


async def _record_tree_tombstones(
    session: AsyncSession,
    kb_id: uuid.UUID,
    *,
    note_ids: list[uuid.UUID] | None = None,
    folder_ids: list[uuid.UUID] | None = None,
) -> None:
    """记录目录树删除墓碑（不提交），供增量刷新返回已删除节点。"""
    for note_id in note_ids or []:
        session.add(NoteTreeTombstone(kb_id=kb_id, item_type="note", item_id=note_id))
    for folder_id in folder_ids or []:
        session.add(NoteTreeTombstone(kb_id=kb_id, item_type="folder", item_id=folder_id))


async def _purge_expired_trash(session: AsyncSession, kb_id: uuid.UUID) -> None:
    """惰性清理超过 30 天的回收站笔记（单用户本地应用，无需常驻定时器）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRASH_RETENTION_DAYS)
    rows = (
        (
            await session.execute(
                select(Note).where(Note.kb_id == kb_id, Note.status == "trash")
            )
        )
        .scalars()
        .all()
    )
    expired: list[uuid.UUID] = []
    for note in rows:
        raw = _lifecycle(note).get("trashed_at")
        try:
            trashed_at = datetime.fromisoformat(str(raw)) if raw else note.updated_at
            if trashed_at.tzinfo is None:
                trashed_at = trashed_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            trashed_at = note.updated_at
        if trashed_at < cutoff:
            expired.append(note.id)
    if expired:
        await _record_tree_tombstones(session, kb_id, note_ids=expired)
        await session.execute(delete(Note).where(Note.id.in_(expired)))
        await session.commit()
    # 墓碑只需覆盖增量同步窗口；顺手清理过期记录。
    tombstone_cutoff = datetime.now(timezone.utc) - timedelta(days=TREE_TOMBSTONE_RETENTION_DAYS)
    stale = await session.execute(
        delete(NoteTreeTombstone).where(
            NoteTreeTombstone.kb_id == kb_id,
            NoteTreeTombstone.created_at < tombstone_cutoff,
        )
    )
    if stale.rowcount:
        await session.commit()


async def _ensure_tag_path(
    session: AsyncSession, kb_id: uuid.UUID, raw_name: str
) -> NoteTag | None:
    """按 `父/子` 路径创建标签（幂等），返回叶子标签。"""
    name = raw_name.strip().lstrip("#").strip()
    if not name:
        return None
    name = name[:100]
    parts = [p.strip()[:100] for p in name.split("/") if p.strip()]
    if not parts:
        return None
    parent_id: uuid.UUID | None = None
    leaf: NoteTag | None = None
    for index in range(len(parts)):
        # 允许同名叶子在不同父级下共存：唯一键使用完整路径
        full = "/".join(parts[: index + 1])[:100]
        tag = (
            await session.execute(
                select(NoteTag).where(NoteTag.kb_id == kb_id, NoteTag.name == full)
            )
        ).scalar_one_or_none()
        if tag is None:
            tag = NoteTag(kb_id=kb_id, name=full, parent_id=parent_id)
            session.add(tag)
            await session.flush()
        elif parent_id is not None and tag.parent_id is None:
            tag.parent_id = parent_id
        parent_id = tag.id
        leaf = tag
    return leaf


async def _sync_note_tags(
    session: AsyncSession, note: Note, names: list[str]
) -> None:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = raw.strip().lstrip("#").strip()
        if name and name not in seen:
            seen.add(name)
            normalized.append(name)
    tag_ids: list[uuid.UUID] = []
    for name in normalized:
        tag = await _ensure_tag_path(session, note.kb_id, name)
        if tag is not None:
            tag_ids.append(tag.id)
    await session.execute(delete(NoteTagLink).where(NoteTagLink.note_id == note.id))
    for tag_id in tag_ids:
        session.add(NoteTagLink(note_id=note.id, tag_id=tag_id))
    # 标签存于关联表，不会自动更新 notes.updated_at；显式触碰以便
    # `/tree?since=` 增量刷新能把这篇笔记的标签变化带到客户端。
    note.updated_at = datetime.now(timezone.utc)
    await session.flush()



def _snippet(body: str, terms: list[str], width: int = 180) -> str:
    text = re.sub(r"\s+", " ", (body or "").replace("---", " ")).strip()
    if not text:
        return ""
    lower = text.lower()
    pos = -1
    for term in terms:
        found = lower.find(term.lower())
        if found >= 0 and (pos < 0 or found < pos):
            pos = found
    if pos < 0:
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def _bigrams(text: str) -> set[str]:
    clean = re.sub(r"```[\s\S]*?```", " ", text or "")
    clean = re.sub(r"\[\[([^\[\]]+?)\]\]", r"\1", clean)
    clean = re.sub(r"[#>*_`~\-\[\]()]|\s+", "", clean)
    if len(clean) < 2:
        return set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


async def _get_folder(
    session: AsyncSession, kb_id: uuid.UUID, folder_id: uuid.UUID
) -> NoteFolder:
    folder = await session.get(NoteFolder, folder_id)
    if folder is None or folder.kb_id != kb_id:
        raise HTTPException(404, "分组不存在")
    return folder


async def _validate_folder(
    session: AsyncSession, kb_id: uuid.UUID, folder_id: uuid.UUID | None
) -> None:
    if folder_id is None:
        return
    folder = await session.get(NoteFolder, folder_id)
    if folder is None or folder.kb_id != kb_id:
        raise HTTPException(400, "分组不存在")


async def _get_parent_note(
    session: AsyncSession, kb_id: uuid.UUID, parent_note_id: uuid.UUID
) -> Note:
    parent = await session.get(Note, parent_note_id)
    if parent is None or parent.kb_id != kb_id:
        raise HTTPException(400, "父笔记不存在")
    if parent.status != "active":
        raise HTTPException(400, "父笔记不在工作区")
    return parent


async def _validate_note_parent(
    session: AsyncSession,
    kb_id: uuid.UUID,
    note_id: uuid.UUID | None,
    parent_note_id: uuid.UUID | None,
) -> Note | None:
    """校验父笔记可访问，并拒绝把笔记挂到自身或自己的后代下。"""
    if parent_note_id is None:
        return None
    if note_id is not None and parent_note_id == note_id:
        raise HTTPException(400, "不能把笔记移到自身下级")
    parent = await _get_parent_note(session, kb_id, parent_note_id)
    seen = {parent.id}
    cursor = parent
    guard = 0
    while cursor.parent_note_id is not None and guard < 1000:
        guard += 1
        if note_id is not None and cursor.parent_note_id == note_id:
            raise HTTPException(400, "不能把笔记移到自己的子笔记下")
        if cursor.parent_note_id in seen:
            raise HTTPException(400, "笔记层级存在循环引用")
        seen.add(cursor.parent_note_id)
        cursor = await session.get(Note, cursor.parent_note_id)
        if cursor is None:
            break
    return parent


async def _note_descendant_ids(
    session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID
) -> list[uuid.UUID]:
    """BFS 返回全部子笔记 id（不含自身），用于级联分组与状态。"""
    seen: set[uuid.UUID] = set()
    frontier = [note_id]
    while frontier and len(seen) < 5000:
        rows = (
            (
                await session.execute(
                    select(Note.id).where(
                        Note.kb_id == kb_id, Note.parent_note_id.in_(frontier)
                    )
                )
            )
            .scalars()
            .all()
        )
        frontier = [row for row in rows if row not in seen]
        seen.update(frontier)
    return list(seen)


async def _move_subtree_folder(
    session: AsyncSession,
    kb_id: uuid.UUID,
    note_id: uuid.UUID,
    folder_id: uuid.UUID | None,
) -> None:
    """父笔记换分组时，所有子笔记跟随，保证同一子树不跨分组。"""
    descendants = await _note_descendant_ids(session, kb_id, note_id)
    if descendants:
        await session.execute(
            update(Note).where(Note.id.in_(descendants)).values(folder_id=folder_id)
        )


async def _next_note_sort(
    session: AsyncSession,
    kb_id: uuid.UUID,
    folder_id: uuid.UUID | None,
    parent_note_id: uuid.UUID | None = None,
) -> int:
    if parent_note_id is not None:
        # 子笔记只与同一父笔记下的兄弟排序，分组不是它们的同级节点。
        values = list(
            (
                await session.execute(
                    select(Note.sort_order).where(
                        Note.kb_id == kb_id, Note.parent_note_id == parent_note_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return (max(values) + 1) if values else 0
    stmt = select(Note.sort_order).where(
        Note.kb_id == kb_id, Note.parent_note_id.is_(None)
    )
    stmt = stmt.where(Note.folder_id == folder_id) if folder_id else stmt.where(
        Note.folder_id.is_(None)
    )
    values = list((await session.execute(stmt)).scalars().all())
    folder_stmt = select(NoteFolder.sort_order).where(NoteFolder.kb_id == kb_id)
    folder_stmt = folder_stmt.where(
        NoteFolder.parent_id == folder_id
        if folder_id
        else NoteFolder.parent_id.is_(None)
    )
    values.extend((await session.execute(folder_stmt)).scalars().all())
    return (max(values) + 1) if values else 0


async def _next_folder_sort(
    session: AsyncSession, kb_id: uuid.UUID, parent_id: uuid.UUID | None
) -> int:
    stmt = select(NoteFolder.sort_order).where(NoteFolder.kb_id == kb_id)
    stmt = stmt.where(NoteFolder.parent_id == parent_id) if parent_id else stmt.where(
        NoteFolder.parent_id.is_(None)
    )
    values = list((await session.execute(stmt)).scalars().all())
    note_stmt = select(Note.sort_order).where(
        Note.kb_id == kb_id, Note.status == "active"
    )
    note_stmt = note_stmt.where(
        Note.folder_id == parent_id if parent_id else Note.folder_id.is_(None)
    )
    values.extend((await session.execute(note_stmt)).scalars().all())
    return (max(values) + 1) if values else 0


async def _rebuild_links(session: AsyncSession, kb_id: uuid.UUID, note: Note) -> None:
    """重建 note_links 与笔记→Wiki 关联。

    支持两种正文语法：
    - ``[[标题]]``：按标题匹配笔记，按标题 / slug 匹配 Wiki 页面；
    - ``[@标题](kiwi://note/<id>)`` / ``[@标题](kiwi://wiki/<id>)``：编辑器
      @ 提及的持久化形式，按 id 精确匹配。

    命中的 Wiki 页面写入 ``props_json.wiki_links``，供知识图谱和反向链接使用。
    """
    body = strip_code(note.body_md or "")
    await session.execute(delete(NoteLink).where(NoteLink.from_note_id == note.id))

    targets = set(LINK_RE.findall(body))
    mention_note_ids = {
        uuid.UUID(raw) for raw in NOTE_MENTION_RE.findall(body)
        if raw.lower() != str(note.id).lower()
    }
    mention_wiki_ids = {
        uuid.UUID(raw) for raw in WIKI_MENTION_RE.findall(body)
        if raw.lower() != str(note.id).lower()
    }

    rows: list[Note] = []
    if targets:
        rows.extend(
            (
                await session.execute(
                    select(Note).where(Note.kb_id == kb_id, Note.title.in_(list(targets)))
                )
            )
            .scalars()
            .all()
        )
    if mention_note_ids:
        rows.extend(
            (
                await session.execute(
                    select(Note).where(
                        Note.kb_id == kb_id, Note.id.in_(list(mention_note_ids))
                    )
                )
            )
            .scalars()
            .all()
        )

    by_id = {n.id: n for n in rows}
    linked: set[uuid.UUID] = set()
    # 旧语法按标题建链；同一次保存内按目标去重，避免同一笔记被链接两次。
    title_to_id = {n.title: n.id for n in rows}
    for title in targets:
        target_id = title_to_id.get(title)
        if target_id is None or target_id == note.id or target_id in linked:
            continue
        linked.add(target_id)
        session.add(
            NoteLink(from_note_id=note.id, to_note_id=target_id, context_text=title)
        )
    # @ 提及按 id 建链，不依赖标题是否被后续改名。
    for target_id in mention_note_ids:
        if target_id == note.id or target_id in linked or target_id not in by_id:
            continue
        linked.add(target_id)
        session.add(
            NoteLink(
                from_note_id=note.id,
                to_note_id=target_id,
                context_text=by_id[target_id].title,
            )
        )

    wiki_rows: list[WikiPage] = []
    if targets:
        wiki_rows.extend(
            (
                await session.execute(
                    select(WikiPage).where(
                        WikiPage.kb_id == kb_id,
                        or_(
                            WikiPage.title.in_(list(targets)),
                            WikiPage.slug.in_(list(targets)),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
    if mention_wiki_ids:
        wiki_rows.extend(
            (
                await session.execute(
                    select(WikiPage).where(
                        WikiPage.kb_id == kb_id, WikiPage.id.in_(list(mention_wiki_ids))
                    )
                )
            )
            .scalars()
            .all()
        )
    wiki_ids = sorted({str(page.id) for page in wiki_rows})
    props = dict(note.props_json or {})
    if wiki_ids:
        props["wiki_links"] = wiki_ids
    else:
        props.pop("wiki_links", None)
    if props != (note.props_json or {}):
        note.props_json = props
    await session.flush()



def _import_props(note: Note) -> dict:
    return (note.props_json or {}).get("import") or {}


