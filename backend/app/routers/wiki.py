"""Wiki 路由：页面读写、总览仪表盘、图谱、健康检查（Lint）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    IngestJob,
    KnowledgeBase,
    LearningAnnotation,
    LearningTopic,
    Note,
    NoteLink,
    Source,
    StudyProfile,
    WikiLink,
    WikiLintReport,
    WikiPage,
)
from app.db.session import get_session
from app.schemas.wiki import (
    GraphData,
    GraphEdge,
    GraphNode,
    LintIssue,
    LintReport,
    LintReportOut,
    WikiOverview,
    WikiPageCreate,
    WikiPageOut,
    WikiPageSummary,
    WikiPageUpdate,
    WikiSchemaOut,
    WikiSchemaUpdate,
)
from app.services import audit
from app.services.compile_eligibility import note_compile_eligible
from app.services.wiki_links import WIKI_LINK_RE, extract_links, strip_code

logger = logging.getLogger("kiwi.wiki")

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


# --------------------------------------------------------------------------- #
# 公共查询
# --------------------------------------------------------------------------- #
async def _get_page(session: AsyncSession, kb_id: uuid.UUID, page_id: uuid.UUID) -> WikiPage:
    page = await session.get(WikiPage, page_id)
    if page is None or page.kb_id != kb_id:
        raise HTTPException(404, "Wiki 页面不存在")
    return page


def _norm_link(value: str) -> str:
    return value.strip().lower().replace("_", "-")


async def _kb_embedding_model(session: AsyncSession, kb_id: uuid.UUID) -> str | None:
    """知识库配置的 embedding 模型（None → 系统默认）。"""
    kb = await session.get(KnowledgeBase, kb_id)
    return kb.embedding_model if kb is not None else None


async def _link_count(session: AsyncSession, page_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(WikiLink).where(WikiLink.to_page_id == page_id)
        )
    ).scalar_one()


async def _link_counts(session: AsyncSession, kb_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """本库所有页面的入链计数（一次聚合，避免总览 N+1）。"""
    rows = (
        await session.execute(
            select(WikiLink.to_page_id, func.count())
            .join(WikiPage, WikiLink.from_page_id == WikiPage.id)
            .where(WikiPage.kb_id == kb_id)
            .group_by(WikiLink.to_page_id)
        )
    ).all()
    return {row[0]: int(row[1]) for row in rows}


async def _annotation_counts(session: AsyncSession, kb_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(LearningAnnotation.target_id, func.count())
            .where(
                LearningAnnotation.kb_id == kb_id,
                LearningAnnotation.target_type == "wiki",
            )
            .group_by(LearningAnnotation.target_id)
        )
    ).all()
    return {str(row[0]): int(row[1]) for row in rows}


async def _mastery_state(
    session: AsyncSession, kb_id: uuid.UUID
) -> tuple[dict[str, float], dict]:
    """返回 {slug: mastery} 与学习画像聚合状态。"""
    profile = (
        await session.execute(
            select(StudyProfile)
            .where(StudyProfile.kb_id == kb_id)
            .order_by(StudyProfile.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    topics = (
        await session.execute(
            select(LearningTopic).where(
                LearningTopic.kb_id == kb_id, LearningTopic.active.is_(True)
            )
        )
    ).scalars().all()

    mastery: dict[str, float] = {}
    if profile and isinstance(profile.mastery, dict):
        for slug, value in profile.mastery.items():
            try:
                mastery[str(slug)] = round(float(value), 4)
            except (TypeError, ValueError):
                continue
    for topic in topics:
        mastery.setdefault(topic.slug, round(float(topic.mastery_score or 0), 4))

    topic_count = len(topics)
    covered = sum(1 for t in topics if mastery.get(t.slug, 0) > 0)
    weak = sum(1 for t in topics if t.weak_flag)
    values = [mastery.get(t.slug, 0.0) for t in topics]
    status = {
        "has_profile": profile is not None,
        "onboarded": bool(profile.onboarded) if profile else False,
        "goal_type": profile.goal_type if profile else None,
        "topic_count": topic_count,
        "covered_topic_count": covered,
        "mastery_coverage": round(covered / topic_count, 4) if topic_count else 0.0,
        "average_mastery": round(sum(values) / len(values), 4) if values else 0.0,
        "weak_count": weak,
        "target_date": profile.target_date.isoformat()
        if profile and profile.target_date
        else None,
    }
    return mastery, status


def _summary_line(body_md: str) -> str:
    """取正文第一段有意义的纯文本，用于卡片摘要。"""
    for raw in strip_code(body_md or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "---", "|", ">", "-", "*", "```", "~~~")):
            continue
        line = WIKI_LINK_RE.sub(lambda m: m.group(1), line)
        line = re.sub(r"[`*_~]", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        if line:
            return line[:180] + ("…" if len(line) > 180 else "")
    return ""


def _tags_of(page: WikiPage) -> list[str]:
    raw = (page.frontmatter_json or {}).get("tags")
    if isinstance(raw, list):
        return [str(t) for t in raw if str(t).strip()]
    return []


def _enrich_summary(
    page: WikiPage,
    *,
    links: dict[uuid.UUID, int],
    annotations: dict[str, int],
    mastery: dict[str, float],
) -> WikiPageSummary:
    summary = WikiPageSummary.model_validate(page, from_attributes=True)
    summary.link_count = links.get(page.id, 0)
    summary.summary = _summary_line(page.body_md)
    summary.tags = _tags_of(page)
    summary.mastery = mastery.get(page.slug)
    summary.annotation_count = annotations.get(str(page.id), 0)
    summary.source_count = len(page.compiled_from_source_ids or [])
    return summary


# --------------------------------------------------------------------------- #
# 总览与列表
# --------------------------------------------------------------------------- #
@router.get("/overview", response_model=WikiOverview)
async def overview(kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    """Wiki 总览聚合（数据来自 PG 聚合，不触发向量检索）。"""
    pages = list(
        (
            await session.execute(
                select(WikiPage)
                .where(WikiPage.kb_id == kb_id)
                .order_by(WikiPage.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    type_dist: dict[str, int] = {}
    for p in pages:
        type_dist[p.page_type] = type_dist.get(p.page_type, 0) + 1

    pending_compile = (
        await session.execute(
            select(func.count())
            .select_from(Source)
            .where(Source.kb_id == kb_id, Source.status == "parsed")
        )
    ).scalar_one()
    pending_review = (
        await session.execute(
            select(func.count())
            .select_from(Source)
            .where(Source.kb_id == kb_id, Source.parse_quality == "review")
        )
    ).scalar_one()
    # 可与「编译全部笔记」一起进入 Wiki 的活跃笔记数。与 compile-all 使用同一套
    # 资格判断：数据表行笔记、待办汇总、只读导入材料不计入候选。
    candidate_notes = (
        (
            await session.execute(
                select(Note).where(Note.kb_id == kb_id, Note.status == "active")
            )
        )
        .scalars()
        .all()
    )
    note_compile_candidates = sum(1 for note in candidate_notes if note_compile_eligible(note))

    links = await _link_counts(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    mastery, study_status = await _mastery_state(session, kb_id)

    summaries = [
        _enrich_summary(p, links=links, annotations=annotations, mastery=mastery)
        for p in pages[:500]
    ]

    # 最近活动：导入/编译任务 + 页面更新，合并成时间线
    activity: list[dict] = []
    jobs = (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.kb_id == kb_id)
            .order_by(IngestJob.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    source_ids = list({j.source_id for j in jobs if j.source_id})
    source_titles: dict[uuid.UUID, str] = {}
    if source_ids:
        rows = (
            await session.execute(
                select(Source.id, Source.title).where(Source.id.in_(source_ids))
            )
        ).all()
        source_titles = {r.id: r.title for r in rows}
    note_ids = list({j.note_id for j in jobs if j.note_id})
    note_titles: dict[uuid.UUID, str] = {}
    if note_ids:
        rows = (
            await session.execute(
                select(Note.id, Note.title).where(Note.id.in_(note_ids))
            )
        ).all()
        note_titles = {r.id: r.title for r in rows}
    for job in jobs:
        activity.append(
            {
                "at": job.created_at.isoformat(),
                "kind": job.kind,
                "status": job.status,
                "title": note_titles.get(job.note_id)
                or source_titles.get(job.source_id, "未知素材"),
                "detail": job.error or f"进度 {round((job.progress or 0) * 100)}%",
                "job_id": str(job.id),
                "note_id": str(job.note_id) if job.note_id else None,
                "source_id": str(job.source_id),
                "progress": float(job.progress or 0.0),
            }
        )
    for page in pages[:6]:
        activity.append(
            {
                "at": page.updated_at.isoformat(),
                "kind": "wiki",
                "status": "updated",
                "title": page.title,
                "detail": f"v{page.version}" + (" · 人工编辑" if page.human_edited else ""),
            }
        )
    activity.sort(key=lambda item: item.get("at") or "", reverse=True)

    return WikiOverview(
        page_count=len(pages),
        page_type_distribution=type_dist,
        pending_compile_count=pending_compile,
        pending_review_count=pending_review,
        note_compile_candidate_count=note_compile_candidates,
        human_edited_count=sum(1 for p in pages if p.human_edited),
        study_status=study_status,
        recent_activity=activity[:12],
        pages=summaries,
    )


@router.get("", response_model=list[WikiPageSummary])
async def list_pages(
    kb_id: uuid.UUID,
    page_type: str | None = Query(None),
    q: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(WikiPage).where(WikiPage.kb_id == kb_id)
    if page_type:
        stmt = stmt.where(WikiPage.page_type == page_type)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(WikiPage.title.ilike(pattern), WikiPage.slug.ilike(pattern)))
    rows = (
        (await session.execute(stmt.order_by(WikiPage.updated_at.desc()))).scalars().all()
    )
    links = await _link_counts(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    mastery, _ = await _mastery_state(session, kb_id)
    return [
        _enrich_summary(p, links=links, annotations=annotations, mastery=mastery)
        for p in rows
    ]


@router.post("", response_model=WikiPageOut, status_code=201)
async def create_page(
    kb_id: uuid.UUID,
    data: WikiPageCreate,
    session: AsyncSession = Depends(get_session),
):
    """人工创建 Wiki 页面；也用于把问答结果回写为综合页（page_type=synthesis）。"""
    if data.page_type not in ("entity", "concept", "summary", "synthesis"):
        raise HTTPException(400, "无效的页面类型")
    title = data.title.strip()
    if not title:
        raise HTTPException(400, "页面标题不能为空")

    from app.services.wiki_compiler import _slugify

    base = (data.slug or await _slugify(title)).strip()[:180] or "page"
    existing = set(
        (
            await session.execute(
                select(WikiPage.slug).where(WikiPage.kb_id == kb_id)
            )
        )
        .scalars()
        .all()
    )
    slug = base
    counter = 2
    while slug in existing:
        slug = f"{base}-{counter}"
        counter += 1

    tags = [t.strip() for t in data.tags if t.strip()]
    page = WikiPage(
        kb_id=kb_id,
        slug=slug,
        page_type=data.page_type,
        title=title,
        body_md=data.body_md or "",
        frontmatter_json={"type": data.page_type, "tags": tags, "sources": []},
        compiled_from_source_ids=[],
        human_edited=True,
    )
    session.add(page)
    await session.commit()
    await session.refresh(page)

    # 派生数据：链接边与向量索引失败不阻塞页面创建
    try:
        from app.services import qdrant_store
        from app.services.embedder import embed_one_async
        from app.services.wiki_compiler import _rebuild_wiki_links

        await _rebuild_wiki_links(session, kb_id)
        await session.commit()
        model = await _kb_embedding_model(session, kb_id)
        vector = await embed_one_async(f"{page.title}\n{page.body_md[:2000]}", model)
        qdrant_store.upsert_wiki_pages(
            kb_id,
            [
                {
                    "vector": vector,
                    "payload": {
                        "page_id": str(page.id),
                        "title": page.title,
                        "slug": page.slug,
                        "body_head": page.body_md[:500],
                        "human_edited": page.human_edited,
                    },
                }
            ],
            model,
        )
    except Exception:  # noqa: BLE001
        pass

    mastery, _ = await _mastery_state(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    out = WikiPageOut.model_validate(page, from_attributes=True)
    out.tags = _tags_of(page)
    out.mastery = mastery.get(page.slug)
    out.backlink_count = await _link_count(session, page.id)
    out.annotation_count = annotations.get(str(page.id), 0)
    return out


# ---- 必须先于 /{page_id} 声明的字面路径 ---- #


@router.get("/graph/data", response_model=GraphData)
async def graph_data(
    kb_id: uuid.UUID,
    include_notes: bool = Query(True),
    page_types: list[str] | None = Query(None),
    human_edited: bool | None = Query(None),
    focus: str | None = Query(None),
    depth: int = Query(2, ge=1, le=3),
    max_nodes: int = Query(400, ge=20, le=2000),
    session: AsyncSession = Depends(get_session),
):
    """知识图谱：Wiki 页面 + 笔记，支持类型/人工编辑过滤与邻域降级。"""
    # 惰性重建引用边：保证图谱永远反映 body 里的最新 [[链接]]（无需重编译/migration）
    from app.services.wiki_compiler import _rebuild_wiki_links

    await _rebuild_wiki_links(session, kb_id)
    await session.commit()

    pages = list(
        (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))).scalars().all()
    )
    links = (
        (
            await session.execute(
                select(WikiLink)
                .join(WikiPage, WikiLink.from_page_id == WikiPage.id)
                .where(WikiPage.kb_id == kb_id)
            )
        )
        .scalars()
        .all()
    )
    mastery, _ = await _mastery_state(session, kb_id)

    selected_types = set(page_types or [])
    wiki_nodes: list[GraphNode] = []
    for p in pages:
        if selected_types and p.page_type not in selected_types:
            continue
        if human_edited is not None and p.human_edited != human_edited:
            continue
        wiki_nodes.append(
            GraphNode(
                id=f"wiki:{p.id}",
                kind="wiki",
                title=p.title,
                page_type=p.page_type,
                link_count=sum(1 for link in links if link.to_page_id == p.id),
                human_edited=p.human_edited,
                mastery=mastery.get(p.slug),
                status="active",
            )
        )
    allowed_wiki = {n.id for n in wiki_nodes}
    wiki_edges = [
        GraphEdge(
            source=f"wiki:{link.from_page_id}",
            target=f"wiki:{link.to_page_id}",
            type=link.link_type,
        )
        for link in links
        if f"wiki:{link.from_page_id}" in allowed_wiki
        and f"wiki:{link.to_page_id}" in allowed_wiki
    ]

    note_nodes: list[GraphNode] = []
    note_edges: list[GraphEdge] = []
    if include_notes:
        notes = list(
            (
                await session.execute(
                    select(Note).where(
                        Note.kb_id == kb_id, Note.status.in_(["active", "archived"])
                    )
                )
            )
            .scalars()
            .all()
        )
        note_by_id = {n.id: n for n in notes}
        nlinks = (
            await session.execute(
                select(NoteLink).where(NoteLink.from_note_id.in_(note_by_id.keys()))
            )
        ).scalars().all()
        in_degree: dict[uuid.UUID, int] = {}
        for link in nlinks:
            in_degree[link.to_note_id] = in_degree.get(link.to_note_id, 0) + 1
        for n in notes:
            note_nodes.append(
                GraphNode(
                    id=f"note:{n.id}",
                    kind="note",
                    title=n.title,
                    page_type="note",
                    link_count=in_degree.get(n.id, 0),
                    mastery=mastery.get(n.title),
                    note_kind=n.kind,
                    status=n.status,
                )
            )
            # 笔记 ↔ Wiki 关联边：手动关联 + 正文 [[Wiki 标题]] 链接
            props = n.props_json or {}
            raw_ids: set[str] = set()
            if props.get("wiki_page_id"):
                raw_ids.add(str(props["wiki_page_id"]))
            for raw in props.get("wiki_links") or []:
                raw_ids.add(str(raw))
            for raw_wiki in raw_ids:
                if f"wiki:{raw_wiki}" in allowed_wiki:
                    note_edges.append(
                        GraphEdge(
                            source=f"note:{n.id}",
                            target=f"wiki:{raw_wiki}",
                            type="note_wiki",
                        )
                    )
        note_edges.extend(
            GraphEdge(
                source=f"note:{link.from_note_id}",
                target=f"note:{link.to_note_id}",
                type="note_link",
            )
            for link in nlinks
            if link.from_note_id in note_by_id and link.to_note_id in note_by_id
        )

    nodes = wiki_nodes + note_nodes
    edges = wiki_edges + note_edges
    total_nodes = len(nodes)
    performance_mode = total_nodes > 160
    truncated = False

    # 超过 max_nodes 或显式 focus：裁成以焦点为中心的 1–depth 跳邻域。
    if focus and any(n.id == focus for n in nodes):
        adjacency: dict[str, set[str]] = {n.id: set() for n in nodes}
        for edge in edges:
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)
        keep = {focus}
        frontier = {focus}
        for _ in range(depth):
            nxt: set[str] = set()
            for nid in frontier:
                nxt |= adjacency.get(nid, set()) - keep
            keep |= nxt
            frontier = nxt
        nodes = [n for n in nodes if n.id in keep]
        edges = [e for e in edges if e.source in keep and e.target in keep]
        truncated = len(nodes) < total_nodes
    elif total_nodes > max_nodes:
        degree: dict[str, int] = {n.id: 0 for n in nodes}
        for edge in edges:
            degree[edge.source] = degree.get(edge.source, 0) + 1
            degree[edge.target] = degree.get(edge.target, 0) + 1
        keep = {
            n.id
            for n in sorted(nodes, key=lambda x: degree.get(x.id, 0), reverse=True)[:max_nodes]
        }
        nodes = [n for n in nodes if n.id in keep]
        edges = [e for e in edges if e.source in keep and e.target in keep]
        truncated = True

    return GraphData(
        nodes=nodes,
        edges=edges,
        performance_mode=performance_mode or truncated,
        truncated=truncated,
        total_nodes=total_nodes,
    )


def _lint_deterministic(
    pages: list[WikiPage], links: list[WikiLink]
) -> list[LintIssue]:
    issues: list[LintIssue] = []
    by_slug: dict[str, WikiPage] = {}
    by_title: dict[str, WikiPage] = {}
    norm_slugs: dict[str, list[WikiPage]] = {}
    for page in pages:
        by_slug[page.slug] = page
        by_title[_norm_link(page.title)] = page
        norm_slugs.setdefault(_norm_link(page.slug), []).append(page)

    # slug 归一化冲突
    for norm, group in norm_slugs.items():
        if len(group) > 1:
            issues.append(
                LintIssue(
                    code="slug_conflict",
                    severity="error",
                    category="slug",
                    message=f"slug 归一化后冲突：{norm}",
                    detail="、".join(p.slug for p in group),
                )
            )

    incoming = {p.id: 0 for p in pages}
    outgoing = {p.id: 0 for p in pages}
    for link in links:
        incoming[link.to_page_id] = incoming.get(link.to_page_id, 0) + 1
        outgoing[link.from_page_id] = outgoing.get(link.from_page_id, 0) + 1

    for page in pages:
        seen_targets: set[str] = set()
        for raw_target in extract_links(page.body_md or ""):
            target = by_slug.get(raw_target.strip()) or by_title.get(_norm_link(raw_target))
            if target is None:
                if raw_target in seen_targets:
                    continue
                seen_targets.add(raw_target)
                issues.append(
                    LintIssue(
                        code="dead_link",
                        severity="warning",
                        category="dead_link",
                        message=f"死链：[[{raw_target}]] 未匹配到页面",
                        page_id=str(page.id),
                        page_title=page.title,
                    )
                )

        if incoming.get(page.id, 0) == 0 and outgoing.get(page.id, 0) == 0:
            issues.append(
                LintIssue(
                    code="orphan_page",
                    severity="warning",
                    category="orphan",
                    message="孤立页面：没有任何入链或出链",
                    page_id=str(page.id),
                    page_title=page.title,
                )
            )

        fm = page.frontmatter_json or {}
        missing = [key for key in ("type", "sources") if key not in fm]
        if missing:
            issues.append(
                LintIssue(
                    code="frontmatter_incomplete",
                    severity="warning",
                    category="frontmatter",
                    message=f"frontmatter 缺少字段：{', '.join(missing)}",
                    page_id=str(page.id),
                    page_title=page.title,
                )
            )
        elif fm.get("type") and fm.get("type") != page.page_type:
            issues.append(
                LintIssue(
                    code="frontmatter_type_mismatch",
                    severity="warning",
                    category="frontmatter",
                    message=f"frontmatter.type={fm.get('type')} 与页面类型 {page.page_type} 不一致",
                    page_id=str(page.id),
                    page_title=page.title,
                )
            )

    # 索引页一致性：识别标题/ slug 为 index 的页面，要求它覆盖全部页面
    index_pages = [
        p
        for p in pages
        if _norm_link(p.slug) in {"index", "wiki-index", "overview"} or p.title.strip() in {"索引", "Index"}
    ]
    if index_pages:
        index = index_pages[0]
        linked = {
            (by_slug.get(t.strip()) or by_title.get(_norm_link(t))).id
            for t in extract_links(index.body_md or "")
            if (by_slug.get(t.strip()) or by_title.get(_norm_link(t))) is not None
        }
        for page in pages:
            if page.id != index.id and page.id not in linked:
                issues.append(
                    LintIssue(
                        code="index_missing_page",
                        severity="info",
                        category="index",
                        message=f"索引页未收录「{page.title}」",
                        page_id=str(page.id),
                        page_title=page.title,
                        detail=index.title,
                    )
                )
    return issues


def _source_drift_issues(
    pages: list[WikiPage], sources: list[Source]
) -> list[LintIssue]:
    """比较素材落盘内容指纹与入库时 sha256，检测源漂移。"""
    source_by_id = {s.id: s for s in sources}
    issues: list[LintIssue] = []
    hash_cache: dict[str, str | None] = {}
    for page in pages:
        for raw_id in page.compiled_from_source_ids or []:
            try:
                sid = uuid.UUID(str(raw_id))
            except (ValueError, TypeError):
                continue
            source = source_by_id.get(sid)
            if source is None:
                continue
            path = Path(source.raw_path)
            if not path.exists():
                issues.append(
                    LintIssue(
                        code="source_missing",
                        severity="warning",
                        category="drift",
                        message=f"来源文件不存在：{source.title}",
                        page_id=str(page.id),
                        page_title=page.title,
                        detail=source.raw_path,
                    )
                )
                continue
            key = str(path)
            if key not in hash_cache:
                try:
                    if path.stat().st_size > 20 * 1024 * 1024:
                        hash_cache[key] = None
                    else:
                        digest = hashlib.sha256()
                        with path.open("rb") as fh:
                            for block in iter(lambda: fh.read(1024 * 1024), b""):
                                digest.update(block)
                        hash_cache[key] = digest.hexdigest()
                except OSError:
                    hash_cache[key] = None
            current = hash_cache[key]
            if current and current != source.sha256:
                issues.append(
                    LintIssue(
                        code="source_drift",
                        severity="warning",
                        category="drift",
                        message=f"源漂移：素材「{source.title}」内容指纹已变化，建议重编译",
                        page_id=str(page.id),
                        page_title=page.title,
                        detail=f"{source.sha256[:12]} → {current[:12]}",
                    )
                )
    return issues


async def _semantic_lint(
    session: AsyncSession, kb_id: uuid.UUID, pages: list[WikiPage]
) -> tuple[list[LintIssue], str, str | None]:
    """LLM 语义审查：矛盾、知识缺口。失败时返回 failed 状态而非让整份报告失败。"""
    try:
        from openai import APIError

        from app.db.models import KnowledgeBase
        from app.services.llm_factory import llm_factory
        from app.services.wiki_compiler import _resolve_llm_config

        kb = await session.get(KnowledgeBase, kb_id)
        if kb is None:
            return [], "failed", "知识库不存在"
        cfg, api_key = await _resolve_llm_config(session, kb)
        client = llm_factory.get_client(cfg.base_url, api_key or None, cfg.model_name)
        material = "\n\n".join(
            f"### {p.title} (slug={p.slug}, type={p.page_type})\n"
            f"{(p.body_md or '')[:1200]}"
            for p in pages[:30]
        )[:18000]
        prompt = (
            "你是知识库健康检查器。审查下面的 Wiki 页面集合，找出：\n"
            "1. 页面之间互相矛盾或数据不一致（category=conflict）；\n"
            "2. 明显缺失的关键概念/知识缺口（category=gap）。\n"
            '只输出 JSON：{"issues":[{"code":"conflict_x","severity":"warning",'
            '"category":"conflict","page_slug":"...","message":"...","detail":"..."}]}。\n'
            "没有问题时输出 {\"issues\":[]}。\n\n" + material
        )
        resp = await client.chat.completions.create(
            model=cfg.model_name,
            messages=[
                {"role": "system", "content": "你是严谨的知识库审查器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        raw = resp.choices[0].message.content or "{}"
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip()
            if raw.lower().startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        slug_to_page = {p.slug: p for p in pages}
        issues: list[LintIssue] = []
        for item in (data.get("issues") or [])[:50]:
            if not isinstance(item, dict):
                continue
            page = slug_to_page.get(str(item.get("page_slug") or ""))
            issues.append(
                LintIssue(
                    code=str(item.get("code") or item.get("category") or "semantic"),
                    severity=str(item.get("severity") or "warning"),
                    category=str(item.get("category") or "semantic"),
                    message=str(item.get("message") or "语义审查发现问题")[:500],
                    page_id=str(page.id) if page else None,
                    page_title=page.title if page else item.get("page_slug"),
                    detail=str(item.get("detail") or "")[:1000] or None,
                )
            )
        return issues, "ok", None
    except ImportError as exc:
        return [], "failed", f"语义审查依赖缺失：{exc}"
    except APIError as exc:
        return [], "failed", f"LLM 调用失败：{exc}"
    except Exception as exc:  # noqa: BLE001
        return [], "failed", f"语义审查失败：{exc}"


@router.get("/lint", response_model=LintReport)
async def lint_deterministic(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """确定性扫描（不发 LLM 调用，适合频繁检查）。"""
    pages = list(
        (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))).scalars().all()
    )
    links = (
        (
            await session.execute(
                select(WikiLink)
                .join(WikiPage, WikiLink.from_page_id == WikiPage.id)
                .where(WikiPage.kb_id == kb_id)
            )
        )
        .scalars()
        .all()
    )
    sources = list(
        (await session.execute(select(Source).where(Source.kb_id == kb_id))).scalars().all()
    )
    issues = _lint_deterministic(pages, links) + _source_drift_issues(pages, sources)
    return LintReport(
        generated_at=datetime.now(timezone.utc),
        summary=_lint_summary(pages, issues),
        issues=issues,
        semantic_status="skipped",
    )


@router.post("/lint", response_model=LintReportOut)
async def run_lint(
    kb_id: uuid.UUID,
    include_semantic: bool = Query(True),
    session: AsyncSession = Depends(get_session),
):
    """执行健康检查并持久化快照：确定性扫描 + 可选 LLM 语义审查。"""
    pages = list(
        (await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))).scalars().all()
    )
    links = (
        (
            await session.execute(
                select(WikiLink)
                .join(WikiPage, WikiLink.from_page_id == WikiPage.id)
                .where(WikiPage.kb_id == kb_id)
            )
        )
        .scalars()
        .all()
    )
    sources = list(
        (await session.execute(select(Source).where(Source.kb_id == kb_id))).scalars().all()
    )
    issues = _lint_deterministic(pages, links) + _source_drift_issues(pages, sources)
    semantic_status = "skipped"
    semantic_error: str | None = None
    if include_semantic and pages:
        semantic_issues, semantic_status, semantic_error = await _semantic_lint(
            session, kb_id, pages
        )
        issues.extend(semantic_issues)
    report = LintReport(
        generated_at=datetime.now(timezone.utc),
        summary=_lint_summary(pages, issues),
        issues=issues,
        semantic_status=semantic_status,
        semantic_error=semantic_error,
    )
    return await _persist_lint_report(
        session, kb_id, report, "full" if include_semantic else "quick"
    )


@router.get("/lint/latest", response_model=LintReportOut | None)
async def latest_lint(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """最近一次已保存的健康检查；没有记录时返回 null。"""
    row = (
        (
            await session.execute(
                select(WikiLintReport)
                .where(WikiLintReport.kb_id == kb_id)
                .order_by(WikiLintReport.generated_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return _lint_out(row) if row is not None else None


@router.get("/lint/history", response_model=list[LintReportOut])
async def lint_history(
    kb_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """健康检查历史，最新的在前。"""
    rows = (
        (
            await session.execute(
                select(WikiLintReport)
                .where(WikiLintReport.kb_id == kb_id)
                .order_by(WikiLintReport.generated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_lint_out(row) for row in rows]


MAX_LINT_REPORTS = 50


async def _persist_lint_report(
    session: AsyncSession,
    kb_id: uuid.UUID,
    report: LintReport,
    trigger: str,
) -> LintReportOut:
    row = WikiLintReport(
        kb_id=kb_id,
        generated_at=report.generated_at,
        trigger=trigger,
        semantic_status=report.semantic_status,
        semantic_error=report.semantic_error,
        summary_json=report.summary,
        issues_json=[issue.model_dump(mode="json") for issue in report.issues],
    )
    session.add(row)
    await session.flush()
    stale_ids = (
        (
            await session.execute(
                select(WikiLintReport.id)
                .where(WikiLintReport.kb_id == kb_id)
                .order_by(WikiLintReport.generated_at.desc())
                .offset(MAX_LINT_REPORTS)
            )
        )
        .scalars()
        .all()
    )
    if stale_ids:
        await session.execute(
            delete(WikiLintReport).where(WikiLintReport.id.in_(stale_ids))
        )
    await session.commit()
    await session.refresh(row)
    return _lint_out(row)


def _lint_out(row: WikiLintReport) -> LintReportOut:
    return LintReportOut(
        id=row.id,
        generated_at=row.generated_at,
        trigger=row.trigger,
        semantic_status=row.semantic_status,
        semantic_error=row.semantic_error,
        summary=row.summary_json or {},
        issues=row.issues_json or [],
    )


def _lint_summary(pages: list[WikiPage], issues: list[LintIssue]) -> dict:
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for issue in issues:
        by_category[issue.category] = by_category.get(issue.category, 0) + 1
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
    return {
        "page_count": len(pages),
        "issue_count": len(issues),
        "error_count": by_severity.get("error", 0),
        "warning_count": by_severity.get("warning", 0),
        "info_count": by_severity.get("info", 0),
        "by_category": by_category,
    }


# --------------------------------------------------------------------------- #
# Schema（LLM Wiki 的结构化规范）
# --------------------------------------------------------------------------- #
async def _require_kb(session: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.get("/schema", response_model=WikiSchemaOut)
async def get_wiki_schema(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """读取本库 Schema；未自定义时返回默认规范并标记 customized=false。"""
    await _require_kb(session, kb_id)
    from app.services.wiki_schema import DEFAULT_WIKI_SCHEMA, MAX_SCHEMA_CHARS, load_schema

    content, customized = load_schema(kb_id)
    return WikiSchemaOut(
        content=content,
        customized=customized,
        default_content=DEFAULT_WIKI_SCHEMA,
        max_chars=MAX_SCHEMA_CHARS,
    )


@router.put("/schema", response_model=WikiSchemaOut)
async def update_wiki_schema(
    payload: WikiSchemaUpdate,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """保存本库 Schema，后续编译立即生效（仅影响下一次编译）。"""
    await _require_kb(session, kb_id)
    from app.services.wiki_schema import (
        DEFAULT_WIKI_SCHEMA,
        MAX_SCHEMA_CHARS,
        save_schema,
    )

    try:
        content = save_schema(kb_id, payload.content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return WikiSchemaOut(
        content=content,
        customized=True,
        default_content=DEFAULT_WIKI_SCHEMA,
        max_chars=MAX_SCHEMA_CHARS,
    )


@router.delete("/schema", status_code=204)
async def reset_wiki_schema(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """删除自定义 Schema，恢复内置默认。"""
    await _require_kb(session, kb_id)
    from app.services.wiki_schema import reset_schema

    reset_schema(kb_id)


@router.post("/reindex")
async def reindex_wiki(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """用知识库当前的 embedding 模型重建全部 Wiki 页向量。

    更换 embedding 模型后，素材需要重新导入，Wiki 页可用本接口重建索引。
    """
    kb = await _require_kb(session, kb_id)
    pages = list(
        (
            await session.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))
        )
        .scalars()
        .all()
    )
    if not pages:
        return {"indexed": 0, "model": kb.embedding_model}

    from app.services import qdrant_store as qs
    from app.services.embedder import embed_texts_async

    try:
        texts = [f"{p.title}\n{p.body_md[:2000]}" for p in pages]
        vectors = await embed_texts_async(texts, kb.embedding_model)
        for p in pages:
            await asyncio.to_thread(
                qs.delete_wiki_page, kb_id, p.id, kb.embedding_model
            )
        points = [
            {
                "vector": v,
                "payload": {
                    "page_id": str(p.id),
                    "title": p.title,
                    "slug": p.slug,
                    "body_head": p.body_md[:500],
                    "human_edited": p.human_edited,
                },
            }
            for p, v in zip(pages, vectors)
        ]
        await asyncio.to_thread(
            qs.upsert_wiki_pages, kb_id, points, kb.embedding_model
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Wiki 向量重建失败：{e}") from e
    return {"indexed": len(pages), "model": kb.embedding_model or "系统默认"}


async def _clear_wiki_content(
    session: AsyncSession, kb: KnowledgeBase
) -> tuple[int, int, int]:
    """兼容入口：实际清理逻辑在 services.compiled_data，供重建与删除复用。"""
    from app.services.compiled_data import clear_wiki_content

    return await clear_wiki_content(session, kb)


@router.post("/rebuild", status_code=202)
async def rebuild_wiki(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """清空本库全部 Wiki 页面，并重新编译全部笔记。

    导入素材解析后已经形成笔记，Wiki 编译只以笔记为输入，不再单独编译素材。
    这是不可撤销的重建操作：人工编辑页、页面批注与健康检查历史会一并删除；
    学习题目 / 复习 / 知识点仅解除页面关联，重新编译后会按 slug 自动关联。
    """
    kb = await _require_kb(session, kb_id)
    deleted_pages, cleared_annotations, cleared_reports = await _clear_wiki_content(
        session, kb
    )
    await audit.record(
        session,
        "wiki.rebuild",
        kb_id=kb_id,
        target_type="kb",
        target_id=kb_id,
        detail={
            "name": kb.name,
            "deleted_pages": deleted_pages,
            "cleared_annotations": cleared_annotations,
            "cleared_reports": cleared_reports,
        },
        note=f"重建 Wiki：{kb.name}（清除 {deleted_pages} 页）",
    )
    await session.commit()

    from app.routers.notes_compile import _prepare_note_compile, _schedule_note_compile
    from app.services import note_compiler

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
    candidates = [note for note in notes if note_compile_eligible(note)]
    note_jobs: list[dict] = []
    empty = 0
    busy = 0
    for note in candidates:
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
        await _schedule_note_compile(job, kb_id, source.id, reused)
        note_jobs.append(
            {
                "job_id": str(job.id),
                "note_id": str(note.id),
                "note_title": note.title,
                "source_id": str(source.id),
            }
        )

    await session.commit()
    return {
        "deleted_pages": deleted_pages,
        "cleared_annotations": cleared_annotations,
        "cleared_lint_reports": cleared_reports,
        "note_jobs": note_jobs,
        "source_jobs": [],
        "count": len(note_jobs),
        "notes": len(candidates),
        "sources": 0,
        "skipped_empty": empty,
        "skipped_busy": busy,
    }


@router.delete("/compiled", response_model=dict)
async def delete_compiled_data(
    kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """删除当前知识库的全部编译数据。

    清空 Wiki 页面、页面向量、批注、Lint 报告、笔记上的 Wiki 关联与笔记
    快照素材，并终止排队中的编译任务；笔记正文、导入素材与学习记录保留。
    """
    kb = await _require_kb(session, kb_id)
    from app.services.compiled_data import delete_all_compiled_data

    stats = await delete_all_compiled_data(session, kb)
    await audit.record(
        session,
        "wiki.compiled.delete",
        kb_id=kb_id,
        target_type="kb",
        target_id=kb_id,
        detail={"name": kb.name, **stats},
        note=f"删除全部编译数据：{kb.name}（{stats['deleted_pages']} 个页面）",
    )
    await session.commit()
    return {"kb_id": str(kb_id), **stats}


# --------------------------------------------------------------------------- #
# 单页
# --------------------------------------------------------------------------- #
@router.get("/{page_id}", response_model=WikiPageOut)
async def get_page(
    page_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    page = await _get_page(session, kb_id, page_id)
    mastery, _ = await _mastery_state(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    out = WikiPageOut.model_validate(page, from_attributes=True)
    out.tags = _tags_of(page)
    out.mastery = mastery.get(page.slug)
    out.backlink_count = await _link_count(session, page.id)
    out.annotation_count = annotations.get(str(page.id), 0)

    source_ids: list[uuid.UUID] = []
    for raw in page.compiled_from_source_ids or []:
        try:
            source_ids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    if source_ids:
        sources = (
            await session.execute(select(Source).where(Source.id.in_(source_ids)))
        ).scalars().all()
        # 素材 → 笔记的反向入口：素材由导入生成时会有一条 source_id 指向它的笔记，
        # 前端据此支持从 Wiki 的「来源」面板跳回原始笔记。
        source_note_rows = (
            await session.execute(
                select(Note.source_id, Note.id).where(
                    Note.kb_id == kb_id,
                    Note.source_id.in_(source_ids),
                    Note.status != "trash",
                )
            )
        ).all()
        note_by_source: dict[uuid.UUID, uuid.UUID] = {}
        for source_id, note_id in source_note_rows:
            note_by_source.setdefault(source_id, note_id)
        out.sources = [
            {
                "id": str(s.id),
                "title": s.title,
                "type": s.type,
                "status": s.status,
                "parse_quality": s.parse_quality,
                "sha256": s.sha256,
                "import_batch_id": s.import_batch_id,
                "parsed_at": s.parsed_at.isoformat() if s.parsed_at else None,
                "note_id": (
                    str(note_by_source[s.id]) if s.id in note_by_source else None
                ),
            }
            for s in sources
        ]

    notes = (
        await session.execute(
            select(Note).where(
                Note.kb_id == kb_id,
                Note.status != "trash",
                Note.props_json["wiki_page_id"].astext == str(page.id),
            )
        )
    ).scalars().all()
    out.related_notes = [
        {"id": str(n.id), "title": n.title, "kind": n.kind, "status": n.status}
        for n in notes
    ]
    return out


@router.get("/{page_id}/backlinks", response_model=list[WikiPageSummary])
async def page_backlinks(
    page_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """反向链接：引用当前页的其他页面。"""
    await _get_page(session, kb_id, page_id)
    in_links = (
        (await session.execute(select(WikiLink).where(WikiLink.to_page_id == page_id)))
        .scalars()
        .all()
    )
    ids = [link.from_page_id for link in in_links]
    if not ids:
        return []
    rows = (await session.execute(select(WikiPage).where(WikiPage.id.in_(ids)))).scalars().all()
    links = await _link_counts(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    mastery, _ = await _mastery_state(session, kb_id)
    return [
        _enrich_summary(p, links=links, annotations=annotations, mastery=mastery)
        for p in rows
    ]


@router.get("/{page_id}/outlinks", response_model=list[WikiPageSummary])
async def page_outlinks(
    page_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """出链列表（本页引用了谁）。"""
    page = await _get_page(session, kb_id, page_id)
    out_links = (
        (await session.execute(select(WikiLink).where(WikiLink.from_page_id == page.id)))
        .scalars()
        .all()
    )
    ids = [link.to_page_id for link in out_links]
    if not ids:
        return []
    rows = (await session.execute(select(WikiPage).where(WikiPage.id.in_(ids)))).scalars().all()
    links = await _link_counts(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    mastery, _ = await _mastery_state(session, kb_id)
    return [
        _enrich_summary(p, links=links, annotations=annotations, mastery=mastery)
        for p in rows
    ]


@router.patch("/{page_id}", response_model=WikiPageOut)
async def update_page(
    page_id: uuid.UUID,
    kb_id: uuid.UUID,
    data: WikiPageUpdate,
    session: AsyncSession = Depends(get_session),
):
    """人工编辑 Wiki 页。正文被修改时默认置 human_edited=true，保护不被编译覆盖。"""
    page = await _get_page(session, kb_id, page_id)
    body_changed = data.body_md is not None and data.body_md != page.body_md
    if data.title is not None:
        page.title = data.title.strip()[:300] or page.title
    if data.page_type is not None:
        if data.page_type not in ("entity", "concept", "summary", "synthesis"):
            raise HTTPException(400, "无效的页面类型")
        page.page_type = data.page_type
    if data.body_md is not None:
        page.body_md = data.body_md
    if body_changed:
        page.version = (page.version or 1) + 1

    frontmatter = dict(page.frontmatter_json or {})
    if data.frontmatter_json is not None:
        frontmatter.update(data.frontmatter_json)
    if data.tags is not None:
        frontmatter["tags"] = [t.strip() for t in data.tags if t.strip()]
    # 人工编辑保存视为已核对源漂移，清除标记
    frontmatter.pop("source_drift", None)
    frontmatter["type"] = page.page_type
    frontmatter["sources"] = list(page.compiled_from_source_ids or [])
    page.frontmatter_json = frontmatter

    if data.human_edited is not None:
        page.human_edited = data.human_edited
    elif body_changed or data.tags is not None or data.title is not None:
        page.human_edited = True

    await session.commit()
    await session.refresh(page)

    # 重建链接边 + 重新索引该页向量（失败不阻塞人工保存）
    try:
        from app.services import qdrant_store
        from app.services.embedder import embed_one_async
        from app.services.wiki_compiler import _rebuild_wiki_links

        await _rebuild_wiki_links(session, kb_id)
        await session.commit()
        model = await _kb_embedding_model(session, kb_id)
        vector = await embed_one_async(f"{page.title}\n{page.body_md[:2000]}", model)
        qdrant_store.upsert_wiki_pages(
            kb_id,
            [
                {
                    "vector": vector,
                    "payload": {
                        "page_id": str(page.id),
                        "title": page.title,
                        "slug": page.slug,
                        "body_head": page.body_md[:500],
                        "human_edited": page.human_edited,
                    },
                }
            ],
            model,
        )
    except Exception:  # noqa: BLE001
        # 索引是派生数据，失败时保留 PG 事实，等待下次编译重建
        pass

    mastery, _ = await _mastery_state(session, kb_id)
    annotations = await _annotation_counts(session, kb_id)
    out = WikiPageOut.model_validate(page, from_attributes=True)
    out.tags = _tags_of(page)
    out.mastery = mastery.get(page.slug)
    out.backlink_count = await _link_count(session, page.id)
    out.annotation_count = annotations.get(str(page.id), 0)
    return out


@router.delete("/{page_id}", status_code=204)
async def delete_page(
    page_id: uuid.UUID, kb_id: uuid.UUID, session: AsyncSession = Depends(get_session)
):
    """删除 Wiki 页面（同时清理链接边与向量索引）。"""
    page = await _get_page(session, kb_id, page_id)
    slug = page.slug
    page_id_str = str(page.id)
    await session.delete(page)
    await session.commit()
    try:
        from app.services import qdrant_store

        model = await _kb_embedding_model(session, kb_id)
        qdrant_store.delete_wiki_page(kb_id, page_id_str, model)
    except Exception:  # noqa: BLE001
        pass
    # 解除笔记与该页的关联，避免悬挂引用
    notes = (
        await session.execute(
            select(Note).where(
                Note.kb_id == kb_id,
                Note.props_json["wiki_page_id"].astext == page_id_str,
            )
        )
    ).scalars().all()
    for note in notes:
        props = dict(note.props_json or {})
        props.pop("wiki_page_id", None)
        note.props_json = props
    await session.commit()
    _ = slug
