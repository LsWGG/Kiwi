"""快速捕获、搜索、相关笔记与图谱。"""

import logging
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CollectionRow,
    Note,
    NoteCollection,
    NoteFolder,
    NoteLink,
    NoteTag,
    NoteTagLink,
    Source,
    WikiPage,
)
from app.db.session import get_session
from app.routers.notes_shared import (
    _bigrams,
    _get_note,
    _next_note_sort,
    _now_iso,
    _rebuild_links,
    _reload_tags,
    _snippet,
    _validate_folder,
)
from app.schemas.note import (
    NoteOut,
    NoteSearchItem,
    NoteSearchOut,
    NoteSummary,
    QuickCaptureIn,
    RelatedNoteItem,
)

logger = logging.getLogger("kiwi.notes.search")

router = APIRouter()

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


def _structured_content(note: Note) -> str:
    """表格 / 画布 / Notebook 的可检索正文：这类笔记的内容在 props_json 里。"""
    props = note.props_json or {}
    parts: list[str] = []
    sheet = props.get("sheet")
    if isinstance(sheet, dict):
        for item in sheet.get("sheets") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if name:
                parts.append(name)
            cells = item.get("cells")
            if isinstance(cells, dict):
                values = [
                    str(cell.get("v"))
                    for cell in cells.values()
                    if isinstance(cell, dict) and cell.get("v") not in (None, "")
                ]
                if values:
                    parts.append(" ".join(values))
    canvas = props.get("canvas_doc")
    if isinstance(canvas, dict):
        for node in canvas.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            text = (
                data.get("label")
                or data.get("text")
                or data.get("title")
                or node.get("label")
                or node.get("text")
            )
            if text:
                parts.append(str(text))
    notebook = props.get("notebook_doc")
    if isinstance(notebook, dict):
        for cell in notebook.get("cells") or []:
            if isinstance(cell, dict):
                source = str(cell.get("source") or "").strip()
                if source:
                    parts.append(source)
    return "\n".join(parts)[:40000]


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
    # 上锁笔记不参与全文检索：标题 / 正文片段都不能通过搜索旁路泄露。
    stmt = (
        select(Note)
        .options(selectinload(Note.tags))
        .where(Note.kb_id == kb_id, Note.lock_hash.is_(None))
    )

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
            await session.execute(
                select(NoteFolder.id, NoteFolder.parent_id).where(NoteFolder.kb_id == kb_id)
            )
        ).all()
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
        # 数据表记录不在正文里，单独按行数据匹配到所属数据表笔记。
        term_row_note_ids = set(
            (
                await session.execute(
                    select(NoteCollection.note_id)
                    .join(CollectionRow, CollectionRow.collection_id == NoteCollection.id)
                    .where(
                        NoteCollection.kb_id == kb_id,
                        NoteCollection.note_id.is_not(None),
                        cast(CollectionRow.data, Text).ilike(pattern),
                    )
                    .limit(2000)
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
            # wiki_page_id 是读取 props_json 的 Python property，不能直接拼 SQL；
            # 这里按 JSONB 文本值匹配关联页面。
            conditions.append(
                Note.props_json["wiki_page_id"].astext.in_(
                    [str(page_id) for page_id in term_wiki_ids]
                )
            )
        if term_source_ids:
            conditions.append(Note.source_id.in_(term_source_ids))
        if term_row_note_ids:
            conditions.append(Note.id.in_(term_row_note_ids))
        stmt = stmt.where(or_(*conditions))

    rows = (await session.execute(stmt.limit(2000))).scalars().all()

    # 数据表记录文本，供评分与摘要使用。
    database_ids = [note.id for note in rows if note.kind == "database"]
    row_text_map: dict[uuid.UUID, str] = {}
    if database_ids:
        buckets: dict[uuid.UUID, list[str]] = {}
        row_pairs = (
            await session.execute(
                select(NoteCollection.note_id, CollectionRow.data)
                .join(CollectionRow, CollectionRow.collection_id == NoteCollection.id)
                .where(NoteCollection.note_id.in_(database_ids))
                .order_by(CollectionRow.sort_order, CollectionRow.created_at)
            )
        ).all()
        for note_id, data in row_pairs:
            if not isinstance(data, dict):
                continue
            text = " | ".join(str(value) for value in data.values() if value not in (None, ""))
            if text:
                buckets.setdefault(note_id, []).append(text)
        row_text_map = {note_id: "\n".join(texts)[:40000] for note_id, texts in buckets.items()}

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
        extra_text = (
            row_text_map.get(note.id, "") if note.kind == "database" else _structured_content(note)
        )
        extra_lower = extra_text.lower()
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
            if tl in extra_lower:
                score += 2 + min(extra_lower.count(tl), 5) * 0.2
                matched.append("content")
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
        body_matches = any(term.lower() in body_lower for term in terms)
        content_matches = any(term.lower() in extra_lower for term in terms)
        snippet_source = note.body_md or ""
        # 结构化内容命中而正文没有命中时，摘要展示表格 / 记录 / 画布里的原文。
        if content_matches and not body_matches:
            snippet_source = extra_text
        snippet = _snippet(snippet_source or note.title, terms)
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
        link.to_note_id if link.from_note_id == note_id else link.from_note_id for link in links
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
                    Note.lock_hash.is_(None),
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
                    Note.lock_hash.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    source_body = source.body_md or ""
    source_grams = _bigrams(source_body) if len(source_body) > 20 else set()
    source_lower = source_body.lower()
    results: list[tuple[float, Note, list[str], float, bool]] = []
    for candidate in candidates:
        reasons: list[str] = []
        score = 0.0
        linked = candidate.id in linked_ids
        similarity = 0.0
        duplicate = False
        shared = source_tags & {t.name for t in candidate.tags}
        if shared:
            score += 3 * len(shared)
            reasons.append("共享标签：" + "、".join(sorted(shared)[:3]))
        if linked:
            score += 2.5
            reasons.append("双向链接")
        if source_grams:
            grams = _bigrams(candidate.body_md or "")
            if grams:
                overlap = len(source_grams & grams)
                similarity = overlap / max(1, len(source_grams | grams))
                containment = overlap / max(1, min(len(source_grams), len(grams)))
                if overlap >= 5 and similarity > 0.02:
                    score += similarity * 12
                    reasons.append(f"内容相似度 {round(similarity * 100)}%")
                # 两份笔记的词汇高度重合，很可能是一份副本；已链接的不再提示重复。
                if not linked and containment >= 0.7 and min(len(source_grams), len(grams)) >= 30:
                    duplicate = True
                    score += 4
                    reasons.append(f"可能重复：内容重合 {round(containment * 100)}%")
        title = (candidate.title or "").strip()
        # 正文以纯文本提到标题时，顺手建议补成 [[双向链接]]。
        if not linked and len(title) >= 2 and title.lower() in source_lower:
            score += 2
            reasons.append("正文提及标题")
        if score > 0 and reasons:
            results.append((score, candidate, reasons, round(similarity, 4), duplicate))
    results.sort(key=lambda item: (-item[0], -item[1].updated_at.timestamp()))
    return [
        RelatedNoteItem(
            note=NoteSummary.model_validate(note, from_attributes=True),
            score=round(score, 3),
            reasons=reasons,
            linked=note.id in linked_ids,
            similarity=similarity,
            duplicate=duplicate,
        )
        for score, note, reasons, similarity, duplicate in results[:12]
    ]


@router.get("/graph", response_model=dict)
async def note_graph(
    kb_id: uuid.UUID,
    include_wiki: bool = True,
    status: str = "active",
    session: AsyncSession = Depends(get_session),
):
    """笔记（及可选 Wiki 页面）图谱节点与边，供编辑模式图谱筛选。"""
    note_stmt = select(Note).where(Note.kb_id == kb_id, Note.lock_hash.is_(None))
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
            (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))).scalars().all()
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
