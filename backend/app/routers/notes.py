"""笔记路由：工作区目录树、CRUD、标签、模板、搜索、生命周期、[[标题]] 双向链接。"""

import asyncio
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import Text, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import (
    CollectionRow,
    ImportBatch,
    IngestJob,
    KnowledgeBase,
    Note,
    NoteAttachment,
    NoteCollection,
    NoteFolder,
    NoteLink,
    NoteTag,
    NoteTagLink,
    NoteTemplate,
    Source,
    WikiPage,
)
from app.db.session import get_session
from app.services.notebook_kernel import kernel_manager
from app.schemas.note import (
    LinkCreate,
    LinkMetaIn,
    LinkMetaOut,
    NoteArchiveOut,
    NoteBacklinkOut,
    NoteCompileOut,
    NoteCompileStatusOut,
    NoteCopyIn,
    NoteCreate,
    NoteFolderCreate,
    NoteFolderOut,
    NoteFolderUpdate,
    NoteImportStartOut,
    NoteImportStatusOut,
    NoteOut,
    NoteSearchItem,
    NoteSearchOut,
    NoteStudyPointOut,
    NoteStudyPointsIn,
    NoteSummary,
    NoteTagCreate,
    NoteTagOut,
    NoteTagsSet,
    NoteTagUpdate,
    NoteTemplateCreate,
    NoteTemplateOut,
    NoteTemplateUpdate,
    NoteTemplateUseIn,
    NoteTransferIn,
    NoteTrashOut,
    NoteTreeOut,
    NoteUpdate,
    NoteWikiLinkIn,
    NoteWikiLinkOut,
    QuickCaptureIn,
    RelatedNoteItem,
    RemoteFileImportIn,
    ReorderIn,
    TableImportOut,
    TablePreviewOut,
)
from app.services import import_service, ingest_service, note_compiler, upload_session
from app.services.file_security import (
    MAX_DIRECT_UPLOAD_BYTES,
    FileInspection,
    FileRejected,
    inspect_upload,
)
from app.services.link_fetcher import LinkFetchError, fetch_and_extract, fetch_meta
from app.services.remote_file import SSRFError, fetch_remote_file
from app.services.note_database import (
    default_views_for,
    ensure_collection,
    ensure_row_note,
    normalize_row_data,
)
from app.services.table_import import (
    MAX_TABLE_BYTES,
    TABLE_EXT,
    TableImportError,
    parse_table,
    preview_payload,
)

router = APIRouter(prefix="/api/notes", tags=["notes"])

LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
# 编辑器里的 @ 提及持久化为 `[@标题](kiwi://note/<id>)`（可带 display / height 参数）。
# 反向链接、相关笔记和笔记图谱都应把它当作真实入链，而不是只认旧的 [[标题]]。
NOTE_MENTION_RE = re.compile(r"\]\(kiwi://note/([0-9a-fA-F-]{36})(?:\?[^)]*)?\)")
WIKI_MENTION_RE = re.compile(r"\]\(kiwi://wiki/([0-9a-fA-F-]{36})(?:\?[^)]*)?\)")
TRASH_RETENTION_DAYS = 30

BUILTIN_TEMPLATES: list[dict] = [
    {
        "name": "文献笔记",
        "description": "记录论文、书籍或报告的来源、摘要、关键论点与个人评注。",
        "icon": "bookOpen",
        "title_pattern": "文献笔记：",
        "body_md": (
            "## 来源\n\n- 作者：\n- 出处：\n- 年份：\n\n"
            "## 摘要\n\n\n\n## 关键论点\n\n1. \n2. \n3. \n\n"
            "## 个人评注\n\n\n\n## 关联概念\n\n- [[相关笔记]]\n"
        ),
        "tags_json": ["文献"],
        "sort_order": 0,
    },
    {
        "name": "会议记录",
        "description": "记录会议日期、参与人、议题、决议与待办事项。",
        "icon": "calendar",
        "title_pattern": "{{date}} 会议记录",
        "body_md": (
            "## 会议信息\n\n- 日期：{{date}}\n- 参与人：\n- 议题：\n\n"
            "## 讨论要点\n\n- \n\n## 决议\n\n- \n\n"
            "## 待办\n\n- [ ] 事项（负责人 / 截止日期）\n"
        ),
        "tags_json": ["会议"],
        "sort_order": 1,
    },
    {
        "name": "概念卡片",
        "description": "用定义、示例与关联概念快速建立可链接的知识卡片。",
        "icon": "sparkle",
        "title_pattern": "概念：",
        "body_md": (
            "## 定义\n\n\n\n## 示例\n\n\n\n## 易混概念\n\n- \n\n"
            "## 关联概念\n\n- [[相关笔记]]\n"
        ),
        "tags_json": ["概念"],
        "sort_order": 2,
    },
    {
        "name": "学习笔记",
        "description": "按知识点、易错点、真题摘录与个人总结组织学习过程。",
        "icon": "target",
        "title_pattern": "学习笔记：",
        "body_md": (
            "## 知识点\n\n\n\n## 易错点\n\n- \n\n"
            "## 真题摘录\n\n> 题目：\n>\n> 解析：\n\n## 个人总结\n\n\n\n"
            "## 关联知识页\n\n- [[相关知识点]]\n"
        ),
        "tags_json": ["学习"],
        "sort_order": 3,
    },
]


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
        await session.execute(delete(Note).where(Note.id.in_(expired)))
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
    await session.flush()


async def _ensure_builtin_templates(
    session: AsyncSession, kb_id: uuid.UUID
) -> None:
    existing = set(
        (
            await session.execute(
                select(NoteTemplate.name).where(
                    NoteTemplate.kb_id == kb_id, NoteTemplate.is_builtin.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    added = False
    for item in BUILTIN_TEMPLATES:
        if item["name"] in existing:
            continue
        session.add(
            NoteTemplate(
                kb_id=kb_id,
                name=item["name"],
                description=item["description"],
                icon=item["icon"],
                title_pattern=item["title_pattern"],
                body_md=item["body_md"],
                tags_json=list(item["tags_json"]),
                props_json={},
                is_builtin=True,
                sort_order=item["sort_order"],
            )
        )
        added = True
    if added:
        await session.commit()


def _template_title(template: NoteTemplate, override: str | None) -> str:
    title = (override or "").strip()
    if title:
        return title[:300]
    today = datetime.now().strftime("%Y-%m-%d")
    pattern = (template.title_pattern or template.name or "无标题文档").replace(
        "{{date}}", today
    )
    return pattern.strip()[:300] or "无标题文档"


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


async def _next_note_sort(
    session: AsyncSession, kb_id: uuid.UUID, folder_id: uuid.UUID | None
) -> int:
    stmt = select(Note.sort_order).where(Note.kb_id == kb_id)
    stmt = stmt.where(Note.folder_id == folder_id) if folder_id else stmt.where(
        Note.folder_id.is_(None)
    )
    values = (await session.execute(stmt)).scalars().all()
    return (max(values) + 1) if values else 0


async def _next_folder_sort(
    session: AsyncSession, kb_id: uuid.UUID, parent_id: uuid.UUID | None
) -> int:
    stmt = select(NoteFolder.sort_order).where(NoteFolder.kb_id == kb_id)
    stmt = stmt.where(NoteFolder.parent_id == parent_id) if parent_id else stmt.where(
        NoteFolder.parent_id.is_(None)
    )
    values = (await session.execute(stmt)).scalars().all()
    return (max(values) + 1) if values else 0


async def _rebuild_links(session: AsyncSession, kb_id: uuid.UUID, note: Note) -> None:
    """重建 note_links 与笔记→Wiki 关联。

    支持两种正文语法：
    - ``[[标题]]``：按标题匹配笔记，按标题 / slug 匹配 Wiki 页面；
    - ``[@标题](kiwi://note/<id>)`` / ``[@标题](kiwi://wiki/<id>)``：编辑器
      @ 提及的持久化形式，按 id 精确匹配。

    命中的 Wiki 页面写入 ``props_json.wiki_links``，供知识图谱和反向链接使用。
    """
    body = note.body_md or ""
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


@router.get("", response_model=list[NoteSummary])
async def list_notes(
    kb_id: uuid.UUID,
    folder_id: uuid.UUID | None = None,
    status: str = "active",
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Note).where(Note.kb_id == kb_id)
    if status == "all":
        stmt = stmt.where(Note.status.in_(["active", "archived"]))
    else:
        stmt = stmt.where(Note.status == status)
    if folder_id is not None:
        stmt = stmt.where(Note.folder_id == folder_id)
    if q:
        stmt = stmt.where(Note.title.ilike(f"%{q}%"))
    stmt = stmt.order_by(Note.updated_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [NoteSummary.model_validate(n, from_attributes=True) for n in rows]


# ---- 目录树 / 分组 / 排序（必须先于 /{note_id} 声明）----


@router.get("/tree", response_model=NoteTreeOut)
async def note_tree(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """一次返回全部分组与笔记，前端自行组树（数据量小，避免递归接口）。"""
    await _purge_expired_trash(session, kb_id)
    folders = (
        (
            await session.execute(
                select(NoteFolder)
                .where(NoteFolder.kb_id == kb_id)
                .order_by(NoteFolder.sort_order, NoteFolder.created_at)
            )
        )
        .scalars()
        .all()
    )
    notes = (
        (
            await session.execute(
                select(Note)
                .where(Note.kb_id == kb_id, Note.status == "active")
                .order_by(Note.sort_order, Note.created_at)
            )
        )
        .scalars()
        .all()
    )
    return NoteTreeOut(
        folders=[NoteFolderOut.model_validate(f, from_attributes=True) for f in folders],
        notes=[NoteSummary.model_validate(n, from_attributes=True) for n in notes],
    )


@router.post("/folders", response_model=NoteFolderOut, status_code=201)
async def create_folder(
    data: NoteFolderCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _validate_folder(session, kb_id, data.parent_id)
    folder = NoteFolder(
        kb_id=kb_id,
        name=data.name.strip(),
        parent_id=data.parent_id,
        sort_order=await _next_folder_sort(session, kb_id, data.parent_id),
    )
    session.add(folder)
    await session.commit()
    await session.refresh(folder)
    return NoteFolderOut.model_validate(folder, from_attributes=True)


@router.patch("/folders/{folder_id}", response_model=NoteFolderOut)
async def update_folder(
    folder_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteFolderUpdate,
    session: AsyncSession = Depends(get_session),
):
    folder = await _get_folder(session, kb_id, folder_id)
    if data.name is not None:
        folder.name = data.name.strip()
    if data.pinned is not None:
        folder.pinned = data.pinned
    if "parent_id" in data.model_fields_set:
        new_parent = data.parent_id
        if new_parent == folder.id:
            raise HTTPException(400, "不能把分组移入自身")
        await _validate_folder(session, kb_id, new_parent)
        if new_parent is not None:
            # 拒绝移入自身后代（否则成环）
            all_folders = (
                (await session.execute(select(NoteFolder).where(NoteFolder.kb_id == kb_id)))
                .scalars()
                .all()
            )
            parent_of = {f.id: f.parent_id for f in all_folders}
            cursor = new_parent
            while cursor is not None:
                if cursor == folder.id:
                    raise HTTPException(400, "不能把分组移入自身的子分组")
                cursor = parent_of.get(cursor)
            folder.sort_order = await _next_folder_sort(session, kb_id, new_parent)
        folder.parent_id = new_parent
    await session.commit()
    await session.refresh(folder)
    return NoteFolderOut.model_validate(folder, from_attributes=True)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """递归删除分组子树；子树内笔记重挂到被删分组的父级。"""
    folder = await _get_folder(session, kb_id, folder_id)
    all_folders = (
        (await session.execute(select(NoteFolder).where(NoteFolder.kb_id == kb_id)))
        .scalars()
        .all()
    )
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for f in all_folders:
        children.setdefault(f.parent_id, []).append(f.id)
    to_delete: list[uuid.UUID] = []
    stack = [folder.id]
    while stack:
        fid = stack.pop()
        to_delete.append(fid)
        stack.extend(children.get(fid, []))

    await session.execute(
        update(Note)
        .where(Note.kb_id == kb_id, Note.folder_id.in_(to_delete))
        .values(folder_id=folder.parent_id)
    )
    await session.execute(delete(NoteFolder).where(NoteFolder.id.in_(to_delete)))
    await session.commit()


@router.post("/reorder", status_code=204)
async def reorder(
    data: ReorderIn, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """同级批量排序；要求 ordered_ids 恰好是该层级的完整集合。"""
    if data.target == "folder":
        stmt = select(NoteFolder.id).where(NoteFolder.kb_id == kb_id)
        stmt = stmt.where(NoteFolder.parent_id == data.parent_id) if data.parent_id else stmt.where(
            NoteFolder.parent_id.is_(None)
        )
        existing = set((await session.execute(stmt)).scalars().all())
        incoming = set(data.ordered_ids)
        if existing != incoming:
            raise HTTPException(400, "排序列表必须包含该层级全部分组")
        for index, fid in enumerate(data.ordered_ids):
            await session.execute(
                update(NoteFolder).where(NoteFolder.id == fid).values(sort_order=index)
            )
    else:
        stmt = select(Note.id).where(Note.kb_id == kb_id, Note.status == "active")
        stmt = stmt.where(Note.folder_id == data.parent_id) if data.parent_id else stmt.where(
            Note.folder_id.is_(None)
        )
        existing = set((await session.execute(stmt)).scalars().all())
        incoming = set(data.ordered_ids)
        if existing != incoming:
            raise HTTPException(400, "排序列表必须包含该层级全部笔记")
        for index, nid in enumerate(data.ordered_ids):
            await session.execute(update(Note).where(Note.id == nid).values(sort_order=index))
    await session.commit()


# ---- 导入 / 链接（必须先于 /{note_id} 声明）----

ALLOWED_IMPORT_EXT = {".md", ".markdown", ".txt", ".text", ".pdf", ".docx", ".doc"}


def _import_props(note: Note) -> dict:
    return (note.props_json or {}).get("import") or {}


def _link_props(result, url: str, prev: dict | None = None) -> dict:
    props = dict(prev or {})
    props.update(
        {
            "url": url,
            "final_url": result.final_url if result else url,
            "site": result.site if result else "",
            "favicon": result.favicon if result else "",
            "excerpt": result.excerpt if result else "",
            "fetch_status": result.fetch_status if result else "failed",
            "fetch_error": result.error if result else None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return props


@router.post("/import", response_model=NoteImportStartOut, status_code=202)
async def import_file(
    kb_id: uuid.UUID,
    file: UploadFile | None = File(None),
    upload_id: str | None = Form(None),
    batch_id: uuid.UUID | None = Form(None),
    folder_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    compile_now: bool = Form(False),
    session: AsyncSession = Depends(get_session),
):
    """导入文件 → 创建导入笔记 + 后台解析。

    小文件直接 multipart 上传；大文件先走 /api/ingest/uploads 分片上传，
    完成后把 upload_id 传到这里，避免重复传输。
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, folder_id)

    session_upload: upload_session.UploadSession | None = None
    if upload_id:
        try:
            session_upload = upload_session.load_session(upload_id)
            if session_upload.kb_id != str(kb_id):
                raise upload_session.UploadError("上传会话不存在", 404)
            content = upload_session.assemble(session_upload)
        except upload_session.UploadError as exc:
            raise HTTPException(exc.status_code, exc.message) from exc
        filename = session_upload.filename
    elif file is not None:
        filename = file.filename or "upload.md"
        content = await file.read()
        if not content:
            raise HTTPException(400, "空文件")
        if len(content) > MAX_DIRECT_UPLOAD_BYTES:
            raise HTTPException(
                413, f"文件超过 {MAX_DIRECT_UPLOAD_BYTES // (1024 * 1024)}MB，请使用分片上传"
            )
    else:
        raise HTTPException(400, "缺少文件或 upload_id")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMPORT_EXT:
        raise HTTPException(
            415, f"不支持的文件类型 {ext}，允许：{', '.join(sorted(ALLOWED_IMPORT_EXT))}"
        )
    try:
        inspection = inspect_upload(content, filename)
    except FileRejected as exc:
        if session_upload is not None:
            upload_session.abort_session(session_upload)
        raise HTTPException(exc.status_code, exc.message) from exc

    try:
        return await _start_import(
            session,
            kb,
            filename=filename,
            content=content,
            folder_id=folder_id,
            title=title,
            compile_now=compile_now,
            batch_id=batch_id,
            inspection=inspection,
        )
    finally:
        if session_upload is not None:
            upload_session.abort_session(session_upload)


async def _start_import(
    session: AsyncSession,
    kb: KnowledgeBase,
    *,
    filename: str,
    content: bytes,
    folder_id: uuid.UUID | None,
    title: str | None,
    compile_now: bool,
    batch_id: uuid.UUID | None,
    inspection: FileInspection,
    import_meta: dict | None = None,
    provider: str = "upload",
) -> NoteImportStartOut:
    """创建导入笔记并启动后台解析（文件上传与线上文件共用）。"""
    kb_id = kb.id
    user_title = (title or "").strip()
    note = Note(
        kb_id=kb_id,
        title=(user_title or Path(filename).stem.strip() or "未命名文档")[:300],
        kind="import",
        body_md="",
        folder_id=folder_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(session, kb_id, folder_id),
        props_json={
            "import": {
                "status": "parsing",
                "progress": 0.0,
                "filename": filename,
                "title_source": "user" if user_title else "auto",
                "scan_status": inspection.scan_status,
                "scan_detail": inspection.scan_detail,
                "warnings": inspection.warnings,
                **(import_meta or {}),
            }
        },
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    await session.refresh(kb)

    created_batch = False
    if batch_id is not None:
        batch = await session.get(ImportBatch, batch_id)
        if batch is None or batch.kb_id != kb_id:
            raise HTTPException(404, "导入批次不存在")
        if batch.status != "running":
            raise HTTPException(409, "批次已结束，无法继续导入")
    else:
        batch = await import_service.create_batch(
            kb_id, provider=provider, label=filename, expected_count=1
        )
        created_batch = True

    try:
        job_id = await ingest_service.run_ingest(
            content,
            filename,
            kb,
            compile_now=compile_now,
            note_id=note.id,
            batch_id=str(batch.id),
            scan_status=inspection.scan_status,
            scan_detail=inspection.scan_detail,
            source_type=inspection.source_type,
            title=note.title,
        )
        job = await session.get(IngestJob, job_id)
        await import_service.record_item(
            batch.id,
            title=note.title,
            status="submitted",
            source_id=job.source_id if job else None,
            job_id=job_id,
            warnings=inspection.warnings,
        )
    except Exception as e:  # noqa: BLE001
        await import_service.record_item(
            batch.id,
            title=note.title,
            status="failed",
            error=f"启动导入失败：{e}",
            warnings=inspection.warnings,
        )
        note.props_json = {
            **(note.props_json or {}),
            "import": {**_import_props(note), "status": "failed", "error": f"启动导入失败：{e}"},
        }
        await session.commit()
        if created_batch:
            await import_service.mark_closed(batch.id)
        raise HTTPException(500, f"启动导入失败：{e}") from e

    if created_batch:
        await import_service.mark_closed(batch.id)
    return NoteImportStartOut(
        note=NoteOut.model_validate(note, from_attributes=True), job_id=job_id
    )


@router.post("/import-url", response_model=NoteImportStartOut, status_code=202)
async def import_remote_file(
    payload: RemoteFileImportIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """按 URL 下载线上文件 → 创建导入笔记 + 后台解析。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, payload.folder_id)

    try:
        remote = await fetch_remote_file(payload.url)
    except SSRFError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LinkFetchError as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        inspection = inspect_upload(remote.content, remote.filename)
    except FileRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc

    return await _start_import(
        session,
        kb,
        filename=remote.filename,
        content=remote.content,
        folder_id=payload.folder_id,
        title=payload.title,
        compile_now=payload.compile_now,
        batch_id=payload.batch_id,
        inspection=inspection,
        import_meta={
            "remote_url": remote.url,
            "final_url": remote.final_url,
            "content_type": remote.content_type,
        },
        provider="url",
    )


async def _load_table_upload(
    file: UploadFile | None, sheet: str | None, has_header: bool
):
    if file is None:
        raise HTTPException(400, "请选择表格文件")
    filename = file.filename or "table.csv"
    ext = Path(filename).suffix.lower()
    if ext not in TABLE_EXT:
        raise HTTPException(
            415, f"不支持的表格类型 {ext or '（无扩展名）'}，允许：.csv、.xlsx、.xls"
        )
    content = await file.read()
    if not content:
        raise HTTPException(400, "表格文件为空")
    if len(content) > MAX_TABLE_BYTES:
        raise HTTPException(413, "表格文件超过 20MB 上限")
    try:
        table = parse_table(
            content, filename, sheet=(sheet or "").strip() or None, has_header=has_header
        )
    except TableImportError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return filename, table


@router.post("/table-preview", response_model=TablePreviewOut)
async def preview_table_file(
    file: UploadFile = File(...),
    sheet: str | None = Form(None),
    has_header: bool = Form(True),
):
    """解析表格预览：工作表列表、推断字段与样例行。"""
    _, table = await _load_table_upload(file, sheet, has_header)
    return TablePreviewOut(**preview_payload(table))


@router.post("/import-table", response_model=TableImportOut, status_code=201)
async def import_table_file(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    folder_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    sheet: str | None = Form(None),
    has_header: bool = Form(True),
    session: AsyncSession = Depends(get_session),
):
    """把 CSV / Excel 转换成数据表笔记。

    每条数据先只写入集合记录；用户可在表格中勾选一条或多条记录，
    再按需生成可编辑笔记，避免大批量导入产生数百篇空笔记。
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, folder_id)

    filename, table = await _load_table_upload(file, sheet, has_header)
    if not table.rows:
        raise HTTPException(422, "表格没有可导入的数据行")

    base_title = (title or "").strip() or Path(filename).stem.strip() or "导入数据表"
    note_title = base_title[:300]
    if len(table.sheets) > 1:
        note_title = f"{base_title} · {table.sheet}"[:300]

    note = Note(
        kb_id=kb_id,
        title=note_title,
        kind="database",
        body_md="",
        folder_id=folder_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(session, kb_id, folder_id),
        props_json={
            "table_import": {
                "filename": filename,
                "sheet": table.sheet,
                "row_count": len(table.rows),
                "truncated": table.truncated,
            }
        },
    )
    session.add(note)
    await session.flush()

    coll = await ensure_collection(session, note)
    coll.name = note_title[:200]
    coll.schema_json = {"fields": table.fields}
    coll.views_json = default_views_for(table.fields)
    coll.description = (
        f"由 {filename} 导入"
        + (f"（工作表「{table.sheet}」）" if len(table.sheets) > 1 else "")
    )[:500]
    await session.flush()

    session.add_all(
        [
            CollectionRow(
                kb_id=kb_id,
                collection_id=coll.id,
                data=data,
                sort_order=index,
            )
            for index, data in enumerate(table.rows)
        ]
    )

    await session.commit()
    await session.refresh(note)
    return TableImportOut(
        note=NoteOut.model_validate(note, from_attributes=True),
        sheet=table.sheet,
        fields=table.fields,
        row_count=len(table.rows),
        truncated=table.truncated,
    )


@router.get("/{note_id}/import", response_model=NoteImportStatusOut)
async def import_status(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """导入进度（前端 1.5s 轮询）：状态、进度、来源与正文是否可读。"""
    note = await _get_note(session, kb_id, note_id)
    if note.kind != "import":
        raise HTTPException(404, "不是导入笔记")
    imp = _import_props(note)
    job = (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.note_id == note.id)
            .order_by(IngestJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    source = None
    if job is not None:
        source = await session.get(Source, job.source_id)
    elif note.source_id:
        source = await session.get(Source, note.source_id)

    status = imp.get("status")
    if status not in ("importing", "ready", "failed"):
        if job is not None:
            if job.status == "failed":
                status = "failed"
            elif job.status == "succeeded":
                status = "ready"
            else:
                status = "importing"
        else:
            status = "ready" if (note.body_md or "").strip() else "importing"

    progress = imp.get("progress")
    if progress is None:
        progress = job.progress if job is not None else (1.0 if status == "ready" else 0.0)

    return NoteImportStatusOut(
        status=status,
        progress=float(progress or 0.0),
        error=imp.get("error") or (job.error if job is not None else None),
        source_id=source.id if source is not None else note.source_id,
        job_id=job.id if job is not None else None,
        source_status=source.status if source is not None else None,
        parse_quality=(source.parse_quality if source is not None else None)
        or imp.get("parse_quality"),
        parse_engine=source.parse_engine if source is not None else None,
        scan_status=(source.scan_status if source is not None else None)
        or imp.get("scan_status"),
        scan_detail=(source.scan_detail if source is not None else None)
        or imp.get("scan_detail"),
        quality_report=(source.quality_report if source is not None else None) or {},
        warnings=((source.quality_report or {}).get("warnings") if source else None)
        or list(imp.get("warnings") or []),
        body_ready=bool((note.body_md or "").strip()),
    )


@router.post("/link/meta", response_model=LinkMetaOut)
async def link_meta(data: LinkMetaIn):
    """只读取网页元信息（标题 / 站点 / 摘要），供编辑器插入链接卡片。"""
    try:
        result = await fetch_meta(data.url)
    except LinkFetchError as e:
        raise HTTPException(400, str(e)) from e
    return LinkMetaOut(
        url=result.url,
        final_url=result.final_url,
        title=result.title,
        site=result.site,
        excerpt=result.excerpt,
        favicon=result.favicon,
        fetch_status=result.fetch_status,  # type: ignore[arg-type]
        error=result.error,
    )


@router.post("/link", response_model=NoteOut, status_code=201)
async def create_link(
    data: LinkCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """服务端抓取网页正文生成链接笔记；抓取失败降级为书签卡片。"""
    await _validate_folder(session, kb_id, data.folder_id)
    try:
        result = await fetch_and_extract(data.url)
    except LinkFetchError as e:
        raise HTTPException(400, str(e)) from e

    note = Note(
        kb_id=kb_id,
        title=(data.title or result.title or result.site or result.url)[:300],
        body_md=result.markdown,
        kind="link",
        folder_id=data.folder_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(session, kb_id, data.folder_id),
        props_json={"link": _link_props(result, result.url)},
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/link/refresh", response_model=NoteOut)
async def refresh_link(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    if note.kind != "link":
        raise HTTPException(404, "不是链接笔记")
    link = (note.props_json or {}).get("link") or {}
    url = link.get("url") or link.get("final_url")
    if not url:
        raise HTTPException(400, "链接缺少原始地址")
    try:
        result = await fetch_and_extract(url)
    except LinkFetchError as e:
        raise HTTPException(400, str(e)) from e
    if result.fetch_status == "ok" and result.markdown:
        note.body_md = result.markdown
    note.props_json = {**(note.props_json or {}), "link": _link_props(result, url, link)}
    await session.commit()
    await session.refresh(note)
    return NoteOut.model_validate(note, from_attributes=True)


# ---- 标签 ----

@router.get("/tags", response_model=list[NoteTagOut])
async def list_tags(
    kb_id: uuid.UUID,
    q: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(
            NoteTag.id,
            NoteTag.name,
            NoteTag.parent_id,
            func.count(Note.id).label("usage_count"),
            func.max(Note.updated_at).label("last_used_at"),
        )
        .outerjoin(NoteTagLink, NoteTagLink.tag_id == NoteTag.id)
        .outerjoin(
            Note,
            (Note.id == NoteTagLink.note_id) & (Note.status != "trash"),
        )
        .where(NoteTag.kb_id == kb_id)
        .group_by(NoteTag.id)
        .order_by(func.count(Note.id).desc(), NoteTag.name)
    )
    if q:
        stmt = stmt.where(NoteTag.name.ilike(f"%{q.strip()}%"))
    rows = (await session.execute(stmt)).all()
    return [
        NoteTagOut(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            usage_count=row.usage_count,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


@router.post("/tags", response_model=NoteTagOut, status_code=201)
async def create_tag(
    data: NoteTagCreate, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    name = data.name.strip().lstrip("#").strip()
    if not name:
        raise HTTPException(400, "标签名不能为空")
    parent = None
    if data.parent_id is not None:
        parent = await session.get(NoteTag, data.parent_id)
        if parent is None or parent.kb_id != kb_id:
            raise HTTPException(400, "父标签不存在")
    exists = (
        await session.execute(
            select(NoteTag).where(NoteTag.kb_id == kb_id, NoteTag.name == name)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "同名标签已存在")
    tag = NoteTag(kb_id=kb_id, name=name[:100], parent_id=parent.id if parent else None)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return NoteTagOut(id=tag.id, name=tag.name, parent_id=tag.parent_id, usage_count=0)


@router.patch("/tags/{tag_id}", response_model=NoteTagOut)
async def update_tag(
    tag_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTagUpdate,
    session: AsyncSession = Depends(get_session),
):
    tag = await session.get(NoteTag, tag_id)
    if tag is None or tag.kb_id != kb_id:
        raise HTTPException(404, "标签不存在")
    if data.name is not None:
        name = data.name.strip().lstrip("#").strip()
        if not name:
            raise HTTPException(400, "标签名不能为空")
        clash = (
            await session.execute(
                select(NoteTag).where(
                    NoteTag.kb_id == kb_id, NoteTag.name == name, NoteTag.id != tag.id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(409, "同名标签已存在")
        tag.name = name[:100]
    if "parent_id" in data.model_fields_set:
        if data.parent_id == tag.id:
            raise HTTPException(400, "不能把标签挂到自身")
        if data.parent_id is not None:
            parent = await session.get(NoteTag, data.parent_id)
            if parent is None or parent.kb_id != kb_id:
                raise HTTPException(400, "父标签不存在")
            # 防环
            cursor = parent
            guard = 0
            while cursor is not None and guard < 100:
                if cursor.id == tag.id:
                    raise HTTPException(400, "不能把标签移入自身后代")
                cursor = (
                    await session.get(NoteTag, cursor.parent_id)
                    if cursor.parent_id
                    else None
                )
                guard += 1
        tag.parent_id = data.parent_id
    await session.commit()
    await session.refresh(tag)
    usage = (
        await session.execute(
            select(func.count())
            .select_from(NoteTagLink)
            .join(Note, Note.id == NoteTagLink.note_id)
            .where(NoteTagLink.tag_id == tag.id, Note.status != "trash")
        )
    ).scalar_one()
    return NoteTagOut(
        id=tag.id, name=tag.name, parent_id=tag.parent_id, usage_count=usage
    )


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    tag = await session.get(NoteTag, tag_id)
    if tag is None or tag.kb_id != kb_id:
        raise HTTPException(404, "标签不存在")
    await session.execute(
        update(NoteTag).where(NoteTag.parent_id == tag.id).values(parent_id=tag.parent_id)
    )
    await session.delete(tag)
    await session.commit()


@router.put("/{note_id}/tags", response_model=NoteOut)
async def set_note_tags(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTagsSet,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    await _sync_note_tags(session, note, data.names)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


# ---- 模板 ----

@router.get("/templates", response_model=list[NoteTemplateOut])
async def list_templates(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    await _ensure_builtin_templates(session, kb_id)
    rows = (
        (
            await session.execute(
                select(NoteTemplate)
                .where(NoteTemplate.kb_id == kb_id)
                .order_by(NoteTemplate.is_builtin.desc(), NoteTemplate.sort_order, NoteTemplate.name)
            )
        )
        .scalars()
        .all()
    )
    return [NoteTemplateOut.model_validate(t, from_attributes=True) for t in rows]


@router.post("/templates", response_model=NoteTemplateOut, status_code=201)
async def create_template(
    data: NoteTemplateCreate,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    sort_order = data.sort_order
    if sort_order is None:
        values = (
            (
                await session.execute(
                    select(NoteTemplate.sort_order).where(
                        NoteTemplate.kb_id == kb_id, NoteTemplate.is_builtin.is_(False)
                    )
                )
            )
            .scalars()
            .all()
        )
        sort_order = (max(values) + 1) if values else 100
    template = NoteTemplate(
        kb_id=kb_id,
        name=data.name.strip()[:200],
        description=data.description,
        icon=data.icon,
        title_pattern=data.title_pattern[:300],
        body_md=data.body_md,
        tags_json=[t.strip().lstrip("#") for t in data.tags_json if t.strip()],
        props_json=data.props_json,
        is_builtin=False,
        sort_order=sort_order,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return NoteTemplateOut.model_validate(template, from_attributes=True)


async def _get_template(
    session: AsyncSession, kb_id: uuid.UUID, template_id: uuid.UUID
) -> NoteTemplate:
    template = await session.get(NoteTemplate, template_id)
    if template is None or template.kb_id != kb_id:
        raise HTTPException(404, "模板不存在")
    return template


@router.patch("/templates/{template_id}", response_model=NoteTemplateOut)
async def update_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTemplateUpdate,
    session: AsyncSession = Depends(get_session),
):
    template = await _get_template(session, kb_id, template_id)
    if template.is_builtin:
        raise HTTPException(403, "内置模板不可编辑，可克隆后修改")
    for field in ("name", "description", "icon", "title_pattern", "body_md", "sort_order"):
        if field in data.model_fields_set:
            value = getattr(data, field)
            if value is not None:
                setattr(template, field, value.strip() if field == "name" else value)
    if data.tags_json is not None:
        template.tags_json = [t.strip().lstrip("#") for t in data.tags_json if t.strip()]
    if data.props_json is not None:
        template.props_json = {**(template.props_json or {}), **data.props_json}
    await session.commit()
    await session.refresh(template)
    return NoteTemplateOut.model_validate(template, from_attributes=True)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    template = await _get_template(session, kb_id, template_id)
    if template.is_builtin:
        raise HTTPException(403, "内置模板不可删除")
    await session.delete(template)
    await session.commit()


@router.post("/templates/{template_id}/use", response_model=NoteOut, status_code=201)
async def use_template(
    template_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTemplateUseIn,
    session: AsyncSession = Depends(get_session),
):
    template = await _get_template(session, kb_id, template_id)
    await _validate_folder(session, kb_id, data.folder_id)
    title = _template_title(template, data.title)
    body = (template.body_md or "").replace("{{date}}", datetime.now().strftime("%Y-%m-%d"))
    template_props = dict(template.props_json or {})

    # 集合模板：直接在目标数据表中创建一行，并套用标题/标签/正文结构
    collection_note_id = template_props.get("collection_note_id")
    if collection_note_id:
        try:
            db_note_id = uuid.UUID(str(collection_note_id))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, "模板关联的数据表无效") from e
        db_note = await session.get(Note, db_note_id)
        if db_note is None or db_note.kb_id != kb_id or db_note.kind != "database":
            raise HTTPException(400, "模板关联的数据表不存在")
        coll = await ensure_collection(session, db_note)
        fields = (coll.schema_json or {}).get("fields") or []
        raw_data = dict(template_props.get("collection_data") or {})
        title_field = next(
            (f["id"] for f in fields if f["id"] in ("name", "title")), None
        ) or next(
            (f["id"] for f in fields if f.get("type") in ("text", "long_text", "url")),
            None,
        )
        if title_field and (data.title or template.title_pattern):
            raw_data[title_field] = title
        try:
            row_data = normalize_row_data(raw_data, fields)
        except ValueError as e:
            raise HTTPException(400, f"模板属性不合法：{e}") from e
        existing = (
            (
                await session.execute(
                    select(CollectionRow.sort_order).where(
                        CollectionRow.collection_id == coll.id
                    )
                )
            )
            .scalars()
            .all()
        )
        row = CollectionRow(
            kb_id=kb_id,
            collection_id=coll.id,
            data=row_data,
            sort_order=(max(existing) + 1) if existing else 0,
        )
        session.add(row)
        await session.flush()
        note = await ensure_row_note(session, db_note, coll, row)
        note.body_md = body
        note.view_mode = "edit"
        props = dict(note.props_json or {})
        props.update(
            {
                k: v
                for k, v in template_props.items()
                if k not in ("collection_note_id", "collection_data", "collection_id")
            }
        )
        props["template_id"] = str(template.id)
        note.props_json = props
        await _sync_note_tags(session, note, list(template.tags_json or []))
        await _rebuild_links(session, kb_id, note)
        await session.commit()
        await _reload_tags(session, note)
        return NoteOut.model_validate(note, from_attributes=True)

    note = Note(
        kb_id=kb_id,
        title=title,
        body_md=body,
        kind="doc",
        folder_id=data.folder_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(session, kb_id, data.folder_id),
        props_json={**(template.props_json or {}), "template_id": str(template.id)},
    )
    session.add(note)
    await session.flush()
    await _sync_note_tags(session, note, list(template.tags_json or []))
    await _rebuild_links(session, kb_id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


# ---- 快速捕获 ----

@router.post("/quick-capture", response_model=NoteOut, status_code=201)
async def quick_capture(
    data: QuickCaptureIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """快速捕获：标题取首行，正文保留全文；默认落入「收件箱」分组。"""
    folder_id = data.folder_id
    if folder_id is None:
        inbox = (
            await session.execute(
                select(NoteFolder).where(
                    NoteFolder.kb_id == kb_id,
                    NoteFolder.parent_id.is_(None),
                    NoteFolder.name == "收件箱",
                )
            )
        ).scalar_one_or_none()
        if inbox is None:
            inbox = NoteFolder(kb_id=kb_id, name="收件箱", parent_id=None, sort_order=0)
            session.add(inbox)
            await session.flush()
        folder_id = inbox.id
    else:
        await _validate_folder(session, kb_id, folder_id)

    raw = data.text.strip()
    first_line = raw.splitlines()[0].strip()
    fallback = re.sub(r"^[#>\-\*\s]+", "", first_line)[:80] or "快速笔记"
    title = (data.title or fallback).strip()[:300] or "快速笔记"
    note = Note(
        kb_id=kb_id,
        title=title,
        body_md=raw,
        kind="doc",
        folder_id=folder_id,
        status="active",
        view_mode="edit",
        sort_order=await _next_note_sort(session, kb_id, folder_id),
        props_json={"capture": {"at": _now_iso()}},
    )
    session.add(note)
    await session.flush()
    await _rebuild_links(session, kb_id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


# ---- 搜索 / 相关笔记 / 图谱 ----

@router.get("/search", response_model=NoteSearchOut)
async def search_notes(
    kb_id: uuid.UUID,
    q: str = "",
    folder_id: uuid.UUID | None = None,
    tag_ids: list[uuid.UUID] = Query(default=[]),
    kind: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """全文检索：标题 / 正文 / 标签 / 链接元数据，支持组合筛选与片段高亮。"""
    stmt = select(Note).options(selectinload(Note.tags)).where(Note.kb_id == kb_id)

    if status and status != "all":
        if status not in ("active", "archived", "trash"):
            raise HTTPException(400, "无效的状态筛选")
        stmt = stmt.where(Note.status == status)
    else:
        stmt = stmt.where(Note.status.in_(["active", "archived"]))
    if kind:
        stmt = stmt.where(Note.kind == kind)
    if created_from:
        stmt = stmt.where(Note.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Note.created_at <= created_to)
    if updated_from:
        stmt = stmt.where(Note.updated_at >= updated_from)
    if updated_to:
        stmt = stmt.where(Note.updated_at <= updated_to)

    if folder_id is not None:
        folders = (
            (
                await session.execute(
                    select(NoteFolder.id, NoteFolder.parent_id).where(
                        NoteFolder.kb_id == kb_id
                    )
                )
            )
            .all()
        )
        children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for row in folders:
            children.setdefault(row.parent_id, []).append(row.id)
        folder_ids = {folder_id}
        stack = [folder_id]
        while stack:
            current = stack.pop()
            for child in children.get(current, []):
                if child not in folder_ids:
                    folder_ids.add(child)
                    stack.append(child)
        stmt = stmt.where(Note.folder_id.in_(folder_ids))

    if tag_ids:
        sub = (
            select(NoteTagLink.note_id)
            .where(NoteTagLink.tag_id.in_(tag_ids))
            .group_by(NoteTagLink.note_id)
            .having(func.count(func.distinct(NoteTagLink.tag_id)) == len(set(tag_ids)))
        )
        stmt = stmt.where(Note.id.in_(sub))

    terms = [t for t in re.split(r"\s+", q.strip()) if t]
    for term in terms:
        pattern = f"%{term}%"
        # 关联的 Wiki 页面与素材标题也纳入检索范围
        term_wiki_ids = set(
            (
                await session.execute(
                    select(WikiPage.id)
                    .where(
                        WikiPage.kb_id == kb_id,
                        or_(
                            WikiPage.title.ilike(pattern),
                            WikiPage.body_md.ilike(pattern),
                        ),
                    )
                    .limit(500)
                )
            ).scalars()
        )
        term_source_ids = set(
            (
                await session.execute(
                    select(Source.id)
                    .where(Source.kb_id == kb_id, Source.title.ilike(pattern))
                    .limit(500)
                )
            ).scalars()
        )
        conditions = [
            Note.title.ilike(pattern),
            Note.body_md.ilike(pattern),
            cast(Note.props_json, Text).ilike(pattern),
            Note.tags.any(NoteTag.name.ilike(pattern)),
        ]
        if term_wiki_ids:
            conditions.append(Note.wiki_page_id.in_(term_wiki_ids))
        if term_source_ids:
            conditions.append(Note.source_id.in_(term_source_ids))
        stmt = stmt.where(or_(*conditions))

    rows = (await session.execute(stmt.limit(2000))).scalars().all()

    # 关联内容用于评分与摘要（命中关联 Wiki / 素材时也能给出上下文）
    page_ids = {n.wiki_page_id for n in rows if n.wiki_page_id}
    page_map: dict[uuid.UUID, tuple[str, str]] = {}
    if page_ids:
        page_map = {
            pid: (title or "", body or "")
            for pid, title, body in (
                await session.execute(
                    select(WikiPage.id, WikiPage.title, WikiPage.body_md).where(
                        WikiPage.id.in_(page_ids)
                    )
                )
            ).all()
        }
    source_ids = {n.source_id for n in rows if n.source_id}
    source_title_map: dict[uuid.UUID, str] = {}
    if source_ids:
        source_title_map = {
            sid: title
            for sid, title in (
                await session.execute(
                    select(Source.id, Source.title).where(Source.id.in_(source_ids))
                )
            ).all()
        }
    scored: list[tuple[float, Note, str, list[str]]] = []
    for note in rows:
        matched: list[str] = []
        score = 0.0
        title_lower = (note.title or "").lower()
        body_lower = (note.body_md or "").lower()
        tag_names = [t.name for t in note.tags]
        tag_lower = [t.lower() for t in tag_names]
        props_text = str(note.props_json or {}).lower()
        for term in terms:
            tl = term.lower()
            if tl == title_lower:
                score += 12
                matched.append("title")
            elif tl in title_lower:
                score += 6
                matched.append("title")
            if any(tl in t for t in tag_lower):
                score += 5
                matched.append("tags")
            if tl in body_lower:
                score += 2 + min(body_lower.count(tl), 5) * 0.2
                matched.append("body")
            if tl in props_text:
                score += 1
                matched.append("meta")
            if note.wiki_page_id:
                page = page_map.get(note.wiki_page_id)
                if page and tl in f"{page[0]}\n{page[1]}".lower():
                    score += 3
                    matched.append("wiki")
            if note.source_id:
                source_title = source_title_map.get(note.source_id, "")
                if source_title and tl in source_title.lower():
                    score += 2.5
                    matched.append("source")
        if terms and not matched:
            continue
        if not terms:
            score = 1.0
        matched_set = set(matched)
        snippet = _snippet(note.body_md or note.title, terms)
        if matched_set == {"wiki"} and note.wiki_page_id in page_map:
            page = page_map[note.wiki_page_id]
            snippet = _snippet(page[1] or page[0], terms)
        elif matched_set == {"source"}:
            snippet = f"关联素材：{source_title_map.get(note.source_id, '')}"
        scored.append((score, note, snippet, sorted(matched_set)))
    scored.sort(key=lambda item: (-item[0], -item[1].updated_at.timestamp()))
    total = len(scored)
    page = scored[offset : offset + limit]
    items = [
        NoteSearchItem(
            note=NoteSummary.model_validate(note, from_attributes=True),
            snippet=snippet,
            matched_fields=matched,
            score=round(score, 3),
        )
        for score, note, snippet, matched in page
    ]
    return NoteSearchOut(total=total, items=items)


@router.get("/related/{note_id}", response_model=list[RelatedNoteItem])
async def related_notes(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """相关笔记：共享标签（强）、双向链接（强）、正文相似度（弱）。"""
    source = await _get_note(session, kb_id, note_id)
    source_tags = {t.name for t in source.tags}
    links = (
        (
            await session.execute(
                select(NoteLink).where(
                    or_(
                        NoteLink.from_note_id == note_id,
                        NoteLink.to_note_id == note_id,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    linked_ids = {
        link.to_note_id if link.from_note_id == note_id else link.from_note_id
        for link in links
    }

    candidate_ids: set[uuid.UUID] = set(linked_ids)
    if source_tags:
        tag_rows = (
            (
                await session.execute(
                    select(NoteTagLink.note_id)
                    .join(NoteTag, NoteTag.id == NoteTagLink.tag_id)
                    .where(
                        NoteTag.kb_id == kb_id,
                        NoteTag.name.in_(source_tags),
                        NoteTagLink.note_id != note_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        candidate_ids.update(tag_rows)
    recent = (
        (
            await session.execute(
                select(Note.id)
                .where(
                    Note.kb_id == kb_id,
                    Note.id != note_id,
                    Note.status.in_(["active", "archived"]),
                )
                .order_by(Note.updated_at.desc())
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    candidate_ids.update(recent)
    candidate_ids.discard(note_id)
    if not candidate_ids:
        return []

    candidates = (
        (
            await session.execute(
                select(Note)
                .options(selectinload(Note.tags))
                .where(
                    Note.kb_id == kb_id,
                    Note.id.in_(candidate_ids),
                    Note.status.in_(["active", "archived"]),
                )
            )
        )
        .scalars()
        .all()
    )
    source_grams = _bigrams(source.body_md or "") if len(source.body_md or "") > 20 else set()
    results: list[tuple[float, Note, list[str]]] = []
    for candidate in candidates:
        reasons: list[str] = []
        score = 0.0
        shared = source_tags & {t.name for t in candidate.tags}
        if shared:
            score += 3 * len(shared)
            reasons.append("共享标签：" + "、".join(sorted(shared)[:3]))
        if candidate.id in linked_ids:
            score += 2.5
            reasons.append("双向链接")
        if source_grams:
            grams = _bigrams(candidate.body_md or "")
            if grams:
                overlap = len(source_grams & grams)
                if overlap >= 5:
                    similarity = overlap / max(1, len(source_grams | grams))
                    if similarity > 0.02:
                        score += similarity * 12
                        reasons.append(f"内容相似度 {round(similarity * 100)}%")
        if score > 0 and reasons:
            results.append((score, candidate, reasons))
    results.sort(key=lambda item: (-item[0], -item[1].updated_at.timestamp()))
    return [
        RelatedNoteItem(
            note=NoteSummary.model_validate(note, from_attributes=True),
            score=round(score, 3),
            reasons=reasons,
        )
        for score, note, reasons in results[:12]
    ]


@router.get("/graph", response_model=dict)
async def note_graph(
    kb_id: uuid.UUID,
    include_wiki: bool = True,
    status: str = "active",
    session: AsyncSession = Depends(get_session),
):
    """笔记（及可选 Wiki 页面）图谱节点与边，供编辑模式图谱筛选。"""
    note_stmt = select(Note).where(Note.kb_id == kb_id)
    if status == "all":
        note_stmt = note_stmt.where(Note.status.in_(["active", "archived"]))
    else:
        note_stmt = note_stmt.where(Note.status == status)
    notes = (await session.execute(note_stmt)).scalars().all()
    note_ids = {n.id for n in notes}
    links = (
        (
            await session.execute(
                select(NoteLink).where(
                    NoteLink.from_note_id.in_(note_ids),
                    NoteLink.to_note_id.in_(note_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    degree: dict[uuid.UUID, int] = {}
    for link in links:
        degree[link.from_note_id] = degree.get(link.from_note_id, 0) + 1
        degree[link.to_note_id] = degree.get(link.to_note_id, 0) + 1

    nodes: list[dict] = [
        {
            "id": f"note:{n.id}",
            "kind": "note",
            "title": n.title,
            "note_kind": n.kind,
            "status": n.status,
            "link_count": degree.get(n.id, 0),
        }
        for n in notes
    ]
    edges: list[dict] = [
        {
            "source": f"note:{link.from_note_id}",
            "target": f"note:{link.to_note_id}",
            "type": "note_link",
        }
        for link in links
    ]

    if include_wiki:
        pages = (
            (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id)))
            .scalars()
            .all()
        )
        page_ids = {p.id for p in pages}
        nodes.extend(
            {
                "id": f"wiki:{p.id}",
                "kind": "wiki",
                "title": p.title,
                "page_type": p.page_type,
                "link_count": 0,
            }
            for p in pages
        )
        for note in notes:
            page_id = note.wiki_page_id
            if page_id in page_ids:
                edges.append(
                    {
                        "source": f"note:{note.id}",
                        "target": f"wiki:{page_id}",
                        "type": "note_wiki",
                    }
                )
    return {"nodes": nodes, "edges": edges}


# ---- 生命周期 / 回收站 ----

@router.get("/archived", response_model=NoteArchiveOut)
async def archived_notes(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    rows = (
        (
            await session.execute(
                select(Note)
                .options(selectinload(Note.tags))
                .where(Note.kb_id == kb_id, Note.status == "archived")
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return NoteArchiveOut(
        total=len(rows),
        items=[NoteSummary.model_validate(n, from_attributes=True) for n in rows],
    )


@router.get("/trash", response_model=NoteTrashOut)
async def trash_notes(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _purge_expired_trash(session, kb_id)
    rows = (
        (
            await session.execute(
                select(Note)
                .options(selectinload(Note.tags))
                .where(Note.kb_id == kb_id, Note.status == "trash")
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return NoteTrashOut(
        total=len(rows),
        items=[NoteSummary.model_validate(n, from_attributes=True) for n in rows],
        retention_days=TRASH_RETENTION_DAYS,
    )


@router.delete("/trash", status_code=204)
async def empty_trash(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await session.execute(
        delete(Note).where(Note.kb_id == kb_id, Note.status == "trash")
    )
    await session.commit()


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    include_trash: bool = False,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id, include_trash=include_trash)
    return NoteOut.model_validate(note, from_attributes=True)


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
        (await session.execute(select(Note).where(Note.id.in_(ids), Note.kb_id == kb_id)))
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
    sort_order = data.sort_order
    if sort_order is None:
        sort_order = await _next_note_sort(session, kb_id, data.folder_id)
    note = Note(
        kb_id=kb_id,
        title=data.title.strip(),
        body_md=data.body_md,
        kind=data.kind,
        folder_id=data.folder_id,
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
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    if "folder_id" in data.model_fields_set:
        await _validate_folder(session, kb_id, data.folder_id)
        note.folder_id = data.folder_id
    for field in ("title", "body_md", "status", "view_mode", "sort_order"):
        if field in data.model_fields_set:
            val = getattr(data, field)
            if val is not None:
                setattr(note, field, val)
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
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """移入回收站：保留 30 天，期间可恢复；不立即删除关联数据。"""
    note = await _get_note(session, kb_id, note_id)
    previous = note.status if note.status in ("active", "archived") else "active"
    _set_lifecycle(note, trashed_at=_now_iso(), status_before_trash=previous)
    note.status = "trash"
    # 数据表行笔记删除时同步删除对应行，避免留下无法打开的空行
    row_id = (note.props_json or {}).get("collection_row_id")
    if row_id:
        try:
            row = await session.get(CollectionRow, uuid.UUID(str(row_id)))
        except (ValueError, TypeError):
            row = None
        if row is not None and row.note_id == note.id:
            row.note_id = None
            await session.delete(row)
    # 数据表整体移入回收站时，行笔记一并进入回收站
    for child in await _collection_child_notes(session, note):
        if child.status in ("active", "archived"):
            _set_lifecycle(
                child,
                trashed_at=_now_iso(),
                status_before_trash=child.status,
                trashed_with_collection=True,
            )
            child.status = "trash"
    await session.commit()
    if note.kind == "notebook":
        kernel_manager.terminate(str(note_id))


@router.delete("/{note_id}/permanent", status_code=204)
async def permanently_delete_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    if note.status != "trash":
        raise HTTPException(400, "只有回收站中的笔记可以永久删除")
    # 数据表集合 / 行 / 附件由外键级联；导入/链接的 Source 保留
    if note.kind == "database":
        coll = (
            await session.execute(
                select(NoteCollection).where(NoteCollection.note_id == note.id)
            )
        ).scalar_one_or_none()
        if coll is not None:
            child_ids = (
                (
                    await session.execute(
                        select(CollectionRow.note_id).where(
                            CollectionRow.collection_id == coll.id,
                            CollectionRow.note_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for child_id in child_ids:
                child = await session.get(Note, child_id)
                if child is not None and child.id != note.id:
                    await session.delete(child)
    await session.delete(note)
    await session.commit()
    if note.kind == "notebook":
        kernel_manager.purge_note(str(kb_id), str(note_id))


@router.post("/{note_id}/restore", response_model=NoteOut)
async def restore_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id, include_trash=True)
    if note.status != "trash":
        raise HTTPException(400, "笔记不在回收站中")
    lifecycle = _lifecycle(note)
    previous = lifecycle.get("status_before_trash")
    note.status = previous if previous in ("active", "archived") else "active"
    _set_lifecycle(note, trashed_at=None, status_before_trash=None, restored_at=_now_iso())
    # 原分组若已被删除，回到根级
    if note.folder_id is not None:
        folder = await session.get(NoteFolder, note.folder_id)
        if folder is None or folder.kb_id != kb_id:
            note.folder_id = None
    # 行已被删除的行笔记，恢复后降级为普通文档
    row_id = (note.props_json or {}).get("collection_row_id")
    if row_id:
        try:
            row = await session.get(CollectionRow, uuid.UUID(str(row_id)))
        except (ValueError, TypeError):
            row = None
        if row is None or row.note_id is None:
            props = dict(note.props_json or {})
            props.pop("collection_id", None)
            props.pop("collection_note_id", None)
            props.pop("collection_row_id", None)
            note.props_json = props
    # 与数据表一起移入回收站的行笔记一并恢复
    for child in await _collection_child_notes(session, note):
        if child.status == "trash" and _lifecycle(child).get(
            "trashed_with_collection"
        ):
            child_lifecycle = _lifecycle(child)
            child_previous = child_lifecycle.get("status_before_trash")
            child.status = (
                child_previous
                if child_previous in ("active", "archived")
                else "active"
            )
            _set_lifecycle(
                child,
                trashed_at=None,
                status_before_trash=None,
                trashed_with_collection=None,
                restored_at=_now_iso(),
            )
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/archive", response_model=NoteOut)
async def archive_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    note.status = "archived"
    _set_lifecycle(note, archived_at=_now_iso())
    # 行笔记随数据表一起归档（仅标记被本次操作改变的行，避免误改独立归档）
    for child in await _collection_child_notes(session, note):
        if child.status == "active":
            child.status = "archived"
            _set_lifecycle(
                child, archived_at=_now_iso(), archived_with_collection=True
            )
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/unarchive", response_model=NoteOut)
async def unarchive_note(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    if note.status != "archived":
        raise HTTPException(400, "笔记不在归档中")
    note.status = "active"
    _set_lifecycle(note, archived_at=None)
    for child in await _collection_child_notes(session, note):
        if child.status == "archived" and _lifecycle(child).get(
            "archived_with_collection"
        ):
            child.status = "active"
            _set_lifecycle(child, archived_at=None, archived_with_collection=None)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


# ---- 笔记 → Wiki 编译 ----

async def _prepare_note_compile(
    session: AsyncSession, kb_id: uuid.UUID, note: Note
) -> tuple[IngestJob, Source, bool] | None:
    """把任意类型的笔记序列化为 Source 并创建编译任务。

    - 同一笔记始终复用同一个 Source（external_id = note:<id>），不随正文变化堆积素材；
    - 正文未变化时跳过 raw 向量化；内容变化时重新嵌入后编译；
    - 已有进行中的编译任务时返回 None（单篇接口会转成 409）。
    """
    body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
    if not body:
        return None

    running = (
        await session.execute(
            select(IngestJob.id).where(
                IngestJob.kb_id == kb_id,
                IngestJob.note_id == note.id,
                IngestJob.kind == "compile",
                IngestJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if running is not None:
        return None

    content = body.encode("utf-8")
    fingerprint = sha256(content).hexdigest()
    external_id = f"note:{note.id}"

    source = (
        await session.execute(
            select(Source).where(
                Source.kb_id == kb_id, Source.external_id == external_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        # 兼容旧版按内容指纹创建的笔记素材：从该笔记最近一次编译任务回溯。
        last_job = (
            await session.execute(
                select(IngestJob)
                .where(
                    IngestJob.kb_id == kb_id,
                    IngestJob.note_id == note.id,
                    IngestJob.kind == "compile",
                )
                .order_by(IngestJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_job is not None:
            source = await session.get(Source, last_job.source_id)

    rel = Path(settings.upload_dir) / str(kb_id)
    rel.mkdir(parents=True, exist_ok=True)
    raw_path = rel / f"note-{note.id}.md"
    reused = bool(
        source is not None
        and source.sha256 == fingerprint
        and Path(source.raw_path).exists()
    )

    if source is None:
        raw_path.write_bytes(content)
        source = Source(
            kb_id=kb_id,
            type="note",
            title=(note.title or "笔记")[:300],
            raw_path=str(raw_path),
            sha256=fingerprint,
            status="parsed",
            parse_quality="clean",
            external_id=external_id,
        )
        session.add(source)
        await session.flush()
    else:
        old_path = Path(source.raw_path)
        if not reused:
            raw_path.write_bytes(content)
            source.raw_path = str(raw_path)
            source.sha256 = fingerprint
        source.type = "note"
        source.external_id = external_id
        source.title = (note.title or "笔记")[:300]
        source.status = "parsed"
        source.parse_quality = "clean"
        # 旧版本按指纹命名的临时原文，迁移到稳定路径后清理。
        if old_path != raw_path and old_path.exists() and old_path.name.startswith("note-"):
            try:
                old_path.unlink()
            except OSError:
                pass

    job = IngestJob(
        kb_id=kb_id,
        source_id=source.id,
        kind="compile",
        status="pending",
        note_id=note.id,
    )
    session.add(job)
    await session.flush()
    return job, source, reused


def _schedule_note_compile(
    job: IngestJob, kb_id: uuid.UUID, source_id: uuid.UUID, reused: bool
) -> None:
    async def _run() -> None:
        await ingest_service._process_ingest(
            str(job.id),
            kb_id,
            source_id,
            compile_now=True,
            note_id=None,
            embed_raw=not reused,
        )

    ingest_service._running[str(job.id)] = asyncio.create_task(
        _run(), name=f"note-compile:{job.id}"
    )


@router.post("/compile-all", response_model=dict, status_code=202)
async def compile_all_notes(
    kb_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """把工作区全部活跃笔记（文档 / 导入 / 链接 / 数据表 / 画布）编译进 Wiki。"""
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")

    notes = list(
        (
            await session.execute(
                select(Note)
                .where(Note.kb_id == kb_id, Note.status == "active")
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    # 数据表行笔记的内容会随所属数据表一起编译，避免重复送入。
    candidates = [
        note for note in notes if not (note.props_json or {}).get("collection_row_id")
    ]
    jobs: list[dict] = []
    empty = 0
    busy = 0
    selected = 0
    for note in candidates:
        if len(jobs) >= limit:
            break
        selected += 1
        prepared = await _prepare_note_compile(session, kb_id, note)
        if prepared is None:
            body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
            if body:
                busy += 1
            else:
                empty += 1
            continue
        job, source, reused = prepared
        await session.commit()
        _schedule_note_compile(job, kb_id, source.id, reused)
        jobs.append(
            {
                "job_id": str(job.id),
                "note_id": str(note.id),
                "note_title": note.title,
                "source_id": str(source.id),
            }
        )

    await session.commit()
    return {
        "jobs": jobs,
        "count": len(jobs),
        "candidates": len(candidates),
        "skipped_empty": empty,
        "skipped_busy": busy,
        "skipped_limit": max(0, len(candidates) - selected),
    }


@router.post("/{note_id}/compile", response_model=NoteCompileOut, status_code=202)
async def compile_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """把笔记内容（含数据表 / 画布 / 链接）送入编译流水线。"""
    note = await _get_note(session, kb_id, note_id)
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")

    prepared = await _prepare_note_compile(session, kb_id, note)
    if prepared is None:
        body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
        if not body:
            raise HTTPException(400, "该笔记没有可编译的内容")
        raise HTTPException(409, "该笔记正在编译中，请稍后再试")

    job, source, reused = prepared
    job_id = job.id
    source_id = source.id
    await session.commit()
    _schedule_note_compile(job, kb_id, source_id, reused)
    return NoteCompileOut(job_id=job_id, source_id=source_id, reused_source=reused)


@router.get("/{note_id}/compile/status", response_model=NoteCompileStatusOut)
async def note_compile_status(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    await _get_note(session, kb_id, note_id)
    job = (
        await session.execute(
            select(IngestJob)
            .where(
                IngestJob.kb_id == kb_id,
                IngestJob.note_id == note_id,
                IngestJob.kind == "compile",
            )
            .order_by(IngestJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if job is None:
        return NoteCompileStatusOut()
    touched = job.touched_page_ids or []
    return NoteCompileStatusOut(
        job_id=job.id,
        status=job.status,
        progress=float(job.progress or 0.0),
        error=job.error,
        source_id=job.source_id,
        compiled=job.status == "succeeded",
        page_count=len(touched) if isinstance(touched, list) else 0,
        finished_at=job.updated_at,
    )


# ---- 关联 Wiki 页面 ----

@router.get("/{note_id}/wiki", response_model=NoteWikiLinkOut)
async def get_note_wiki(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    page_id = note.wiki_page_id
    if page_id is None:
        return NoteWikiLinkOut()
    page = await session.get(WikiPage, page_id)
    if page is None or page.kb_id != kb_id:
        return NoteWikiLinkOut()
    return NoteWikiLinkOut(wiki_page_id=page.id, slug=page.slug, title=page.title)


@router.put("/{note_id}/wiki", response_model=NoteWikiLinkOut)
async def set_note_wiki(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteWikiLinkIn,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    props = dict(note.props_json or {})
    if data.wiki_page_id is None:
        props.pop("wiki_page_id", None)
        note.props_json = props
        await session.commit()
        return NoteWikiLinkOut()
    page = await session.get(WikiPage, data.wiki_page_id)
    if page is None or page.kb_id != kb_id:
        raise HTTPException(400, "Wiki 页面不存在")
    props["wiki_page_id"] = str(page.id)
    note.props_json = props
    await session.commit()
    return NoteWikiLinkOut(wiki_page_id=page.id, slug=page.slug, title=page.title)


# ---- 学习要点 ----

def _study_points(note: Note) -> list[NoteStudyPointOut]:
    raw = (note.props_json or {}).get("study_points") or []
    out: list[NoteStudyPointOut] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        out.append(
            NoteStudyPointOut(
                id=str(item.get("id") or uuid.uuid4()),
                text=str(item["text"]),
                wiki_slug=item.get("wiki_slug") or None,
                created_at=str(item.get("created_at") or _now_iso()),
            )
        )
    return out


@router.get("/{note_id}/study-points", response_model=list[NoteStudyPointOut])
async def list_study_points(
    note_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    note = await _get_note(session, kb_id, note_id)
    return _study_points(note)


@router.put("/{note_id}/study-points", response_model=list[NoteStudyPointOut])
async def set_study_points(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteStudyPointsIn,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_note(session, kb_id, note_id)
    existing = {p.id: p for p in _study_points(note)}
    points: list[dict] = []
    for point in data.points:
        point_id = str(uuid.uuid4())
        # 内容未变时沿用原 id，便于前端稳定引用
        for old in existing.values():
            if old.text == point.text and old.wiki_slug == (point.wiki_slug or None):
                point_id = old.id
                break
        points.append(
            {
                "id": point_id,
                "text": point.text.strip(),
                "wiki_slug": point.wiki_slug.strip() if point.wiki_slug else None,
                "created_at": existing.get(point_id).created_at
                if point_id in existing
                else _now_iso(),
            }
        )
    props = dict(note.props_json or {})
    props["study_points"] = points
    note.props_json = props
    await session.commit()
    return _study_points(note)


@router.post("/{note_id}/copy", response_model=NoteOut, status_code=201)
async def copy_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteCopyIn,
    session: AsyncSession = Depends(get_session),
):
    """复制笔记到当前知识库；数据表会连同字段、视图和记录一起复制。"""
    src = await _get_note(session, kb_id, note_id)
    folder_id = data.folder_id if "folder_id" in data.model_fields_set else src.folder_id
    await _validate_folder(session, kb_id, folder_id)
    sort_order = await _next_note_sort(session, kb_id, folder_id)
    title = (data.title or f"{src.title} 副本").strip()[:300] or "无标题文档"
    props = deepcopy(src.props_json or {})
    # 置顶状态属于原条目，副本默认不继承
    props.pop("pinned", None)
    if src.kind == "import":
        # 副本不再处于导入流程中，其余元数据（来源、解析质量等）保留
        props.pop("import", None)
    note = Note(
        kb_id=kb_id,
        title=title,
        body_md=src.body_md,
        kind=src.kind,
        folder_id=folder_id,
        source_id=None,
        status="active",
        view_mode=src.view_mode,
        sort_order=sort_order,
        props_json=props,
    )
    session.add(note)
    await session.flush()

    if src.kind == "database":
        src_coll = (
            await session.execute(
                select(NoteCollection).where(NoteCollection.note_id == src.id)
            )
        ).scalar_one_or_none()
        new_coll = await ensure_collection(session, note)
        if src_coll is not None:
            new_coll.description = src_coll.description
            new_coll.schema_json = deepcopy(src_coll.schema_json or {})
            new_coll.views_json = deepcopy(src_coll.views_json or [])
            rows = (
                (
                    await session.execute(
                        select(CollectionRow)
                        .where(CollectionRow.collection_id == src_coll.id)
                        .order_by(CollectionRow.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                new_row = CollectionRow(
                    kb_id=kb_id,
                    collection_id=new_coll.id,
                    data=deepcopy(row.data or {}),
                    sort_order=row.sort_order,
                )
                session.add(new_row)
                await session.flush()
                # 每行副本同样是完整笔记
                await ensure_row_note(session, note, new_coll, new_row)
            await session.flush()

    await _sync_note_tags(session, note, list(src.tag_names))
    await _rebuild_links(session, kb_id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)


@router.post("/{note_id}/transfer", response_model=NoteOut)
async def transfer_note(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: NoteTransferIn,
    session: AsyncSession = Depends(get_session),
):
    """把笔记移动到另一个知识库（可指定目标分组）。"""
    note = await _get_note(session, kb_id, note_id)
    if data.target_kb_id == kb_id:
        raise HTTPException(400, "目标知识库与当前知识库相同")
    target = await session.get(KnowledgeBase, data.target_kb_id)
    if target is None:
        raise HTTPException(404, "目标知识库不存在")
    await _validate_folder(session, target.id, data.folder_id)
    # 必须在改 kb_id 前计算，避免本条记录进入目标库排序统计
    sort_order = await _next_note_sort(session, target.id, data.folder_id)
    tag_names = list(note.tag_names)

    # 跨库后原库的入链/出链都失效，清掉后在新库按 [[标题]] 重建出链
    await session.execute(
        delete(NoteLink).where(
            or_(NoteLink.from_note_id == note.id, NoteLink.to_note_id == note.id)
        )
    )
    await session.execute(delete(NoteTagLink).where(NoteTagLink.note_id == note.id))
    note.kb_id = target.id
    note.folder_id = data.folder_id
    note.sort_order = sort_order
    # 旧库 Source 不再关联，正文已物化在笔记中
    note.source_id = None
    # 关联的 Wiki 页面属于原库，跨库后失效
    props = dict(note.props_json or {})
    props.pop("wiki_page_id", None)
    note.props_json = props
    if tag_names:
        await _sync_note_tags(session, note, tag_names)

    coll = (
        await session.execute(select(NoteCollection).where(NoteCollection.note_id == note.id))
    ).scalar_one_or_none()
    if coll is not None:
        coll.kb_id = target.id
        await session.execute(
            update(CollectionRow)
            .where(CollectionRow.collection_id == coll.id)
            .values(kb_id=target.id)
        )
        # 行笔记是完整笔记，必须随数据表迁移到目标知识库
        for child in await _collection_child_notes(session, note):
            child_tag_names = list(
                (
                    await session.execute(
                        select(NoteTag.name)
                        .join(NoteTagLink, NoteTagLink.tag_id == NoteTag.id)
                        .where(NoteTagLink.note_id == child.id)
                    )
                )
                .scalars()
                .all()
            )
            await session.execute(
                delete(NoteLink).where(
                    or_(
                        NoteLink.from_note_id == child.id,
                        NoteLink.to_note_id == child.id,
                    )
                )
            )
            await session.execute(
                delete(NoteTagLink).where(NoteTagLink.note_id == child.id)
            )
            child.kb_id = target.id
            child.folder_id = data.folder_id
            child.source_id = None
            child_props = dict(child.props_json or {})
            child_props.pop("wiki_page_id", None)
            child.props_json = child_props
            if child_tag_names:
                await _sync_note_tags(session, child, child_tag_names)
            await session.execute(
                update(NoteAttachment)
                .where(NoteAttachment.note_id == child.id)
                .values(kb_id=target.id)
            )
            await _rebuild_links(session, target.id, child)
    await session.execute(
        update(NoteAttachment).where(NoteAttachment.note_id == note.id).values(kb_id=target.id)
    )
    await session.execute(
        update(IngestJob).where(IngestJob.note_id == note.id).values(kb_id=target.id)
    )
    await _rebuild_links(session, target.id, note)
    await session.commit()
    await _reload_tags(session, note)
    return NoteOut.model_validate(note, from_attributes=True)
