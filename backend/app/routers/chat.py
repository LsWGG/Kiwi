"""流式问答路由：检索增强 → LLM 流式生成 → SSE 事件。

检索范围为 Wiki 页面 + 工作区笔记；笔记是素材整理后的最终形态，
因此不再检索 raw_chunks。事件：chunk(citation 内嵌) / citation / done /
error / keepalive。引用严格限定在用户检索范围内（kb_id 边界由检索层强制）。
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, LLMConfig, Note, WikiLink, WikiPage
from app.db.session import get_session
from app.schemas.chat import ChatRequest, Citation, SearchScope
from app.services import attachment_content
from app.services.agent_planner import (
    AgentPlan,
    apply_time_window,
    contextualize_query,
    in_time_window,
    plan_with_llm,
    rules_plan,
    split_queries,
)
from app.services.embedder import is_disabled
from app.services.lexical import tokenize
from app.services.llm_factory import LLMCrypto, llm_factory
from app.services.note_indexer import ensure_notes_indexed
from app.services.retrieval import RetrievalFilters, route_intent, search
from app.services.web_research import search_web

logger = logging.getLogger("kiwi.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _plain_excerpt(text: str) -> str:
    """把 Markdown 片段压成纯文本，便于目标页面按文本精确高亮。"""
    plain = re.sub(r"```[\s\S]*?```", " ", text or "")
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", plain)
    plain = re.sub(r"\[\[([^\]]+)\]\]", r"\1", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"^#{1,6}\s*", "", plain, flags=re.MULTILINE)
    plain = re.sub(r"[*_`>#|~]", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


def _quote_from_chunk(text: str, query: str) -> str:
    """截取命中词附近的一段原文，作为前端跳转后的高亮锚点。"""
    plain = _plain_excerpt(text)
    if not plain:
        return ""
    for token in dict.fromkeys(tokenize(query)):
        if len(token) < 2:
            continue
        index = plain.lower().find(token.lower())
        if index >= 0:
            start = max(0, index - 50)
            return plain[start : start + 180].strip()
    return plain[:160]


def _first_heading(text: str) -> str:
    match = re.search(r"^#{1,6}\s+(.+)$", text or "", flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _retrieval_filters(scope: SearchScope) -> RetrievalFilters:
    return RetrievalFilters(
        note_ids=list(scope.note_ids),
        folder_ids=list(scope.folder_ids),
        note_kinds=list(scope.note_kinds),
        tag_ids=list(scope.tag_ids),
        updated_from=scope.updated_from,
        updated_to=scope.updated_to,
    )


def _agent_queries(query: str) -> list[str]:
    """兼容旧调用方：多角度检索的并列子问题拆分。"""
    return split_queries(query)


async def _plan_request(
    data: ChatRequest,
    query: str,
    *,
    client: Any,
    model: str,
    current_query: str = "",
    history: list[dict] | None = None,
) -> AgentPlan:
    """按开关选择规划方式：Agent 模式用模型规划，其余用规则规划。

    规则规划始终先解析时间窗口；即使 Agent 关闭，「这周我干嘛了」也会先转成
    日期范围再检索，而不是把原句直接丢给检索或联网。``query`` 是补全上下文
    后的检索问题，``current_query`` 是用户这一轮的原话。
    """
    if data.agent:
        return await plan_with_llm(
            query,
            client=client,
            model=model,
            web_allowed=bool(data.web_search),
            current_query=current_query or None,
            history=history,
        )
    return rules_plan(
        query,
        agent=False,
        web_allowed=bool(data.web_search),
        current_query=current_query or None,
    )


async def _search_web_many(
    queries: list[str],
    *,
    limit: int,
    llm_base_url: str,
    llm_api_key: str,
) -> list[dict]:
    """按规划出的联网查询逐条搜索并去重；单条失败不影响其它查询。"""
    merged: list[dict] = []
    seen: set[str] = set()
    errors: list[Exception] = []
    for query in queries[:2]:
        if not query.strip():
            continue
        try:
            results = await search_web(
                query,
                limit=limit,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
            )
        except Exception as exc:  # noqa: BLE001 —— 一条查询失败仍可尝试下一条
            errors.append(exc)
            continue
        for item in results:
            key = str(item.get("url") or "") or (
                f"{item.get('title') or ''}:{str(item.get('snippet') or '')[:60]}"
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        if len(merged) >= limit:
            break
    if not merged and errors:
        raise errors[-1]
    return merged[:limit]


async def _search_many(
    session: AsyncSession,
    queries: list[str],
    kb_ids: list[uuid.UUID],
    *,
    limit: int,
    collection: str,
    filters: RetrievalFilters | None = None,
) -> list[dict]:
    """对多个子问题分别检索，按命中分块去重后合并（保持原顺序）。"""
    if len(queries) == 1:
        return await search(
            session, queries[0], kb_ids, limit=limit, collection=collection, filters=filters
        )
    merged: list[dict] = []
    seen: set[str] = set()
    for query in queries:
        hits = await search(
            session, query, kb_ids, limit=limit, collection=collection, filters=filters
        )
        for hit in hits:
            payload = hit.get("payload") or {}
            key = str(hit.get("id") or "")
            if not key:
                key = (
                    f"{payload.get('note_id') or payload.get('page_id') or ''}:"
                    f"{payload.get('chunk_index', '')}"
                )
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
    return merged[: limit * 2]


async def resolve_llm(
    session: AsyncSession, kb_id: uuid.UUID | None, temp_cfg_id: uuid.UUID | None
):
    """级联解析：页面级 > 知识库 > 系统默认。返回 (base_url, api_key, model)。"""
    cfg: LLMConfig | None = None
    if temp_cfg_id:
        cfg = await session.get(LLMConfig, temp_cfg_id)
    if cfg is None and kb_id:
        kb = await session.get(KnowledgeBase, kb_id)
        if kb and kb.llm_config_id:
            cfg = await session.get(LLMConfig, kb.llm_config_id)
    if cfg is None:
        cfg = (
            (await session.execute(select(LLMConfig).where(LLMConfig.is_default.is_(True))))
            .scalars()
            .first()
        )
    if cfg is None:
        raise HTTPException(400, "未配置大模型连接，请先在设置中添加并设为默认。")
    api_key = LLMCrypto.decrypt(cfg.encrypted_api_key) if cfg.encrypted_api_key else "ollama"
    return cfg, api_key


async def _kb_names(session: AsyncSession, kb_ids: list[uuid.UUID]) -> dict[str, str]:
    if not kb_ids:
        return {}
    rows = (
        await session.execute(
            select(KnowledgeBase.id, KnowledgeBase.name).where(KnowledgeBase.id.in_(kb_ids))
        )
    ).all()
    return {str(k.id): k.name for k in rows}


async def _resolve_scope(session: AsyncSession, scope: SearchScope) -> list[uuid.UUID]:
    """在检索边界内解析 scope：单库 / 多库 / 全局，拒绝越权与空范围。"""
    if scope.scope == "global":
        rows = (await session.execute(select(KnowledgeBase.id))).scalars().all()
        return list(rows)
    if scope.scope not in ("kb", "multi"):
        raise HTTPException(400, "无效的检索范围类型")
    requested = list(dict.fromkeys(scope.kb_ids))
    if not requested:
        raise HTTPException(400, "请选择要检索的知识库")
    if scope.scope == "kb" and len(requested) > 1:
        raise HTTPException(400, "单库检索只能选择一个知识库")
    rows = (
        (await session.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.id.in_(requested))
        ))
        .scalars()
        .all()
    )
    if len(rows) != len(requested):
        raise HTTPException(404, "部分知识库不存在或不可访问")
    return requested


async def _wiki_neighbors(
    session: AsyncSession,
    kb_ids: list[uuid.UUID],
    seed_ids: list[uuid.UUID],
    exclude: set[uuid.UUID],
    max_pages: int = 4,
) -> list[WikiPage]:
    """沿 Wiki 链接关系扩展 1–2 跳，补充概念上下文。"""
    frontier = [pid for pid in seed_ids if pid not in exclude]
    found: list[WikiPage] = []
    for _depth in range(2):
        if not frontier or len(found) >= max_pages:
            break
        rows = (
            await session.execute(
                select(WikiLink.from_page_id, WikiLink.to_page_id).where(
                    WikiLink.from_page_id.in_(frontier)
                )
            )
        ).all()
        next_ids: list[uuid.UUID] = []
        for _from_id, to_id in rows:
            if to_id in exclude or to_id in next_ids:
                continue
            next_ids.append(to_id)
        if not next_ids:
            break
        pages = (
            (
                await session.execute(
                    select(WikiPage).where(
                        WikiPage.id.in_(next_ids), WikiPage.kb_id.in_(kb_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {page.id: page for page in pages}
        frontier = []
        for pid in next_ids:
            page = by_id.get(pid)
            if page is None:
                continue
            exclude.add(pid)
            found.append(page)
            frontier.append(pid)
            if len(found) >= max_pages:
                break
    return found


async def _safe_search_many(*args, **kwargs) -> tuple[list[dict], str]:
    """检索失败（Qdrant 超时等）时降级为空结果，不让整个问答 500。"""
    try:
        return await _search_many(*args, **kwargs), ""
    except Exception as exc:  # noqa: BLE001 —— 向量层故障不应中断问答
        logger.warning(
            "知识库检索失败（collection=%s）：%s",
            kwargs.get("collection"),
            exc,
            exc_info=True,
        )
        return [], "知识库检索暂时不可用，本次将基于联网结果或对话上下文回答。"


@dataclass
class _PreparedChat:
    openai_msgs: list[dict]
    citations: list[Citation]
    intent: str
    cfg: LLMConfig
    client: Any
    model_name: str
    notices: list[str]


async def _prepare_chat(
    session: AsyncSession,
    data: ChatRequest,
    query: str,
    intent: str,
    stage: Callable[[str, str, str, str], None],
) -> _PreparedChat:
    """检索资料并组装 LLM 请求；耗时步骤通过 stage 回调实时上报。"""
    stage("understand", "start", "正在理解问题")
    kb_ids = await _resolve_scope(session, data.scope)
    stage("understand", "done", "已理解问题")

    # 先解析本次模型：Agent 规划与联网检索都复用同一个连接与凭据。
    bound_kb_id = kb_ids[0] if data.scope.scope == "kb" and kb_ids else None
    cfg, api_key = await resolve_llm(session, bound_kb_id, data.llm_config_id)
    model_name = (data.model_override or "").strip() or cfg.model_name
    client = llm_factory.get_client(cfg.base_url, api_key or None, model_name)

    # 规划检索路径：时间窗口、知识库查询、是否联网。规则解析先跑；
    # Agent 模式再让模型补充查询，模型失败 / 超时会回退到规则结果。
    # 追问（「北京」「那上周呢」）先补全成完整问题，再交给规则 / 模型规划。
    context_query = contextualize_query(data.messages) or query
    contextual = context_query != query
    stage(
        "plan",
        "start",
        "正在结合上下文规划检索路径" if contextual else "正在规划检索路径",
    )
    plan = await _plan_request(
        data,
        context_query,
        client=client,
        model=model_name,
        current_query=query,
        history=data.messages[:-1],
    )
    filters = _retrieval_filters(data.scope)
    time_window_ok = apply_time_window(filters, plan.time_window)
    plan_message = "已结合上下文补全追问" if contextual else "检索计划已生成"
    if plan.time_window:
        plan_message = f"已应用时间范围：{plan.time_window.label}"
        if not time_window_ok:
            plan_message = "时间范围与筛选没有交集"
    plan_detail = plan.describe()
    if contextual:
        plan_detail += f" · 补全问题：{context_query[:80]}"
    stage("plan", "done", plan_message, plan_detail)

    # 「这周我干嘛了」这类个人时间问题优先按笔记回答；显式意图仍以用户选择为准。
    if plan.personal and plan.time_window and data.intent in (None, "auto"):
        intent = "note"
    # 意图路由：Wiki 优先（概念/综合）或笔记优先（精确定位、事实核验）
    wiki_limit = 8 if intent == "wiki" else 4
    # 多取一些笔记分块：数据表 / 长文档的相邻行可能排在稍后的名次，
    # 只取 8 条会漏掉尾部记录；合并后仍按笔记去重并受上下文预算约束。
    note_limit = 16
    queries = plan.queries or [context_query]
    notices: list[str] = []
    if plan.time_window and not time_window_ok:
        notices.append(
            f"问题中的时间范围（{plan.time_window.describe()}）与当前筛选没有交集，"
            "本次未检索到内容。"
        )
    wiki_hits: list[dict] = []
    stage("search", "start", "正在检索 Wiki 与笔记")
    if not filters.has_note_constraints:
        wiki_hits, wiki_error = await _safe_search_many(
            session, queries, kb_ids, limit=wiki_limit, collection="wiki"
        )
        if wiki_error:
            notices.append(wiki_error)
    stage("index", "start", "正在同步最新笔记")
    try:
        # 问答前同步刚编辑过的笔记，避免答案落后于用户的最新整理。
        await ensure_notes_indexed(kb_ids)
    except Exception:  # noqa: BLE001 —— 索引失败不影响 Wiki 检索
        logger.warning("笔记索引同步失败，继续检索已有向量", exc_info=True)
    stage("index", "done", "笔记已同步")
    note_hits, note_error = await _safe_search_many(
        session,
        queries,
        kb_ids,
        limit=note_limit,
        collection="note",
        filters=filters,
    )
    if note_error and note_error not in notices:
        notices.append(note_error)
    kb_names = await _kb_names(session, kb_ids)
    stage(
        "search",
        "done",
        "知识库检索完成",
        f"命中 {len(wiki_hits) + len(note_hits)} 个片段",
    )

    # 只有规划判断确实需要外部信息时才联网，并使用规划出的具体查询词，
    # 不再把「这周我干嘛了」这类个人问题原句丢给搜索引擎。
    web_results: list[dict] = []
    web_error = ""
    if data.web_search and plan.use_web:
        stage("web", "start", "正在联网检索")
        try:
            web_results = await _search_web_many(
                plan.web_queries or [context_query],
                limit=3,
                llm_base_url=cfg.base_url,
                llm_api_key=api_key or "",
            )
            if not web_results:
                web_error = "联网检索没有返回结果，本次仅使用知识库内容回答。"
                stage("web", "done", "联网检索完成", "未返回结果")
            else:
                detail = f"获得 {len(web_results)} 条结果"
                if plan.web_queries:
                    detail += f" · {plan.web_queries[0][:60]}"
                stage("web", "done", "联网检索完成", detail)
        except Exception as exc:  # noqa: BLE001 —— 网络失败降级为知识库问答
            logger.warning("问答联网检索失败：%s", exc)
            web_error = (
                "联网检索失败：搜索服务不可用。请检查网络，或在 .env 配置 "
                "KIWI_STUDY_SEARCH_PROVIDER（bing/duckduckgo/searxng/tavily/deepseek）。"
                "本次仅使用知识库内容回答。"
            )
            stage("web", "error", "联网检索失败", "本次仅使用知识库内容")
    elif data.web_search:
        # 用户开了联网，但规划判断问题属于个人记录 / 无需外部信息。
        stage("web", "done", "已跳过联网", plan.reason or "问题优先使用知识库")
    elif plan.wants_web and data.agent:
        # Agent 判断需要联网，但用户没有开启联网开关：只提示，不擅自外联。
        stage("web", "done", "未开启联网", "该问题可能需要外部信息")
        notices.append(
            "该问题可能需要联网信息，但联网开关未开启，本次仅使用知识库回答。"
        )
    if web_error:
        notices.append(web_error)

    context_parts: list[str] = []
    citations: list[Citation] = []
    seen_pages: set[uuid.UUID] = set()
    seen_notes: set[uuid.UUID] = set()

    def add_wiki(
        *,
        page_id: str,
        title: str,
        slug: str,
        body: str,
        kb_id: str,
        label: str = "Wiki",
    ) -> None:
        try:
            pid = uuid.UUID(str(page_id))
        except (ValueError, TypeError):
            return
        if pid in seen_pages:
            return
        seen_pages.add(pid)
        kb_label = kb_names.get(kb_id, "")
        prefix = f"{label}·{kb_label}" if kb_label and len(kb_ids) > 1 else label
        citations.append(
            Citation(
                kb_id=kb_id,
                kb_name=kb_label,
                collection="wiki",
                title=title,
                slug=slug,
                chunk_text=(body or "")[:300],
                target_id=str(pid),
                heading=_first_heading(body) or title,
                quote=_quote_from_chunk(body, query),
            )
        )
        # 资料序号与 citations 下标一致，供模型输出 [n] 引用
        context_parts.append(f"[{len(citations)}] ({prefix}) {title}\n{(body or '')[:1500]}")

    def add_note(
        *,
        note_id: str,
        title: str,
        kind: str,
        text: str,
        kb_id: str,
        anchor: tuple[int, str, str] | None = None,
        attachment_text: str = "",
    ) -> None:
        try:
            nid = uuid.UUID(str(note_id))
        except (ValueError, TypeError):
            return
        if nid in seen_notes:
            return
        seen_notes.add(nid)
        kb_label = kb_names.get(kb_id, "")
        prefix = f"笔记·{kb_label}" if kb_label and len(kb_ids) > 1 else "笔记"
        kind_label = {
            "database": "数据表",
            "canvas": "画布",
            "notebook": "Notebook",
            "link": "链接笔记",
            "import": "导入文档",
            "doc": "文档",
        }.get(kind, "笔记")
        citations.append(
            Citation(
                kb_id=kb_id,
                kb_name=kb_label,
                collection="note",
                title=title,
                slug=None,
                chunk_text=(text or "")[:300],
                target_id=str(nid),
                kind=kind,
                chunk_index=anchor[0] if anchor else 0,
                heading=(anchor[2] if anchor else "") or _first_heading(text),
                quote=_quote_from_chunk(anchor[1] if anchor else text, query),
            )
        )
        # 数据表的行内容可能分布在多个分块中，给笔记更宽的上下文预算。
        body = (text or "")[:2000]
        if attachment_text:
            body = f"{body}\n\n{attachment_text}" if body else attachment_text
        context_parts.append(f"[{len(citations)}] ({prefix}·{kind_label}) {title}\n{body}")

    def add_web(
        *, title: str, url: str, snippet: str, content: str = ""
    ) -> None:
        if any(c.collection == "web" and c.url == url for c in citations):
            return
        citations.append(
            Citation(
                kb_id=None,
                kb_name="",
                collection="web",
                title=title or url,
                slug=None,
                chunk_text=(snippet or content or "")[:300],
                target_id=url,
                heading=title or url,
                quote=(snippet or content or "")[:180],
                url=url,
            )
        )
        context_parts.append(
            f"[{len(citations)}] (联网结果) {title or url}\nURL: {url}\n"
            f"{(content or snippet or '')[:1200]}"
        )

    wiki_entries = [
        (h, str((h.get("payload") or {}).get("page_id") or "")) for h in wiki_hits
    ]

    # 同一条笔记可能命中多个分块：合并相邻高分块，引用时按笔记去重。
    note_groups: dict[str, dict] = {}
    for hit in note_hits:
        payload = hit.get("payload") or {}
        note_id = str(payload.get("note_id") or "")
        if not note_id:
            continue
        group = note_groups.setdefault(
            note_id,
            {
                "kb_id": str(hit.get("kb_id") or ""),
                "title": str(payload.get("title") or ""),
                "kind": str(payload.get("kind") or "doc"),
                "chunks": [],
            },
        )
        text = str(payload.get("text") or "").strip()
        if (
            text
            and all(text != existing for _, existing, _heading in group["chunks"])
            and len(group["chunks"]) < 4
        ):
            group["chunks"].append(
                (
                    int(payload.get("chunk_index") or 0),
                    text,
                    str(payload.get("heading") or ""),
                )
            )

    # 以数据库为准过滤已删除 / 回收站笔记，并取最新标题（向量 payload 可能滞后）。
    note_meta: dict[str, tuple[str, str, dict, str]] = {}
    note_ids: list[uuid.UUID] = []
    for note_id in note_groups:
        try:
            note_ids.append(uuid.UUID(note_id))
        except ValueError:
            continue
    if note_ids:
        rows = (
            await session.execute(
                select(
                    Note.id, Note.title, Note.kind, Note.props_json, Note.body_md
                ).where(
                    Note.id.in_(note_ids),
                    Note.kb_id.in_(kb_ids),
                    Note.status == "active",
                )
            )
        ).all()
        note_meta = {
            str(row.id): (
                row.title,
                row.kind,
                dict(row.props_json or {}),
                row.body_md or "",
            )
            for row in rows
        }

    note_entries = [
        (note_id, group)
        for note_id, group in note_groups.items()
        if note_id in note_meta and group["chunks"]
    ]

    # 时间范围检索：日记按标题日期判断（updated_at 会被待办同步等元数据刷新），
    # 个人回顾时排除自动生成的待办汇总，避免把历史完成项当成这周的产出。
    if plan.time_window:
        kept_entries: list[tuple[str, dict]] = []
        for note_id, group in note_entries:
            title, _kind, props, _body = note_meta[note_id]
            if plan.personal and props.get("todo_hub"):
                continue
            if not in_time_window(title or group["title"], plan.time_window):
                continue
            kept_entries.append((note_id, group))
        note_entries = kept_entries

    # 检索分块里只有 kiwi-embed 元数据；读回上传文件的正文，模型才能回答
    # 「这个脚本怎么实现的」这类问题。按笔记顺序读取，受总字符预算约束。
    attachment_texts: dict[str, str] = {}
    remaining_chars = attachment_content.MAX_TOTAL_CHARS
    files_read = 0
    files_skipped = 0
    for note_id, _group in note_entries:
        if files_read >= attachment_content.MAX_FILES or remaining_chars <= 0:
            break
        body_md = note_meta[note_id][3]
        blocks = attachment_content.embedded_file_blocks(body_md or "")
        if not blocks:
            continue
        items = await asyncio.to_thread(
            attachment_content.read_embedded_attachments,
            body_md,
            query=context_query,
            max_files=attachment_content.MAX_FILES - files_read,
            max_chars=min(attachment_content.MAX_FILE_CHARS, remaining_chars),
            total_chars=remaining_chars,
        )
        if not items:
            files_skipped += len(blocks)
            continue
        attachment_texts[note_id] = attachment_content.format_attachments_for_context(
            items
        )
        remaining_chars -= sum(len(item.text) for item in items)
        files_read += len(items)
    if files_read or files_skipped:
        message = f"已读取 {files_read} 个内嵌附件" if files_read else ""
        if files_skipped:
            skipped = f"{files_skipped} 个附件不可读取（非文本文件或文件缺失）"
            message = f"{message}，{skipped}" if message else skipped
        stage("files", "done", message)

    def feed_wiki() -> None:
        for hit, page_id in wiki_entries:
            payload = hit.get("payload") or {}
            add_wiki(
                page_id=page_id,
                title=str(payload.get("title") or ""),
                slug=str(payload.get("slug") or ""),
                body=str(payload.get("body_head") or ""),
                kb_id=str(hit.get("kb_id") or ""),
            )

    def feed_notes() -> None:
        for note_id, group in note_entries:
            title, kind, _props, _body = note_meta[note_id]
            add_note(
                note_id=note_id,
                title=title or group["title"] or "未命名笔记",
                kind=kind or group["kind"],
                # 按原始分块顺序拼接，避免打乱表格行的语义。
                text="\n\n".join(
                    text for _, text, _heading in sorted(group["chunks"])
                ),
                kb_id=group["kb_id"],
                # 首个分块是分数最高的命中，引用跳转以它为锚点。
                anchor=group["chunks"][0],
                attachment_text=attachment_texts.get(note_id, ""),
            )

    if intent == "note":
        feed_notes()
        feed_wiki()
    else:
        feed_wiki()
        # 沿 Wiki 链接扩展 1–2 跳，补充概念上下文
        seed_ids = [pid for pid in seen_pages]
        neighbors = await _wiki_neighbors(session, kb_ids, seed_ids, seen_pages)
        for page in neighbors:
            add_wiki(
                page_id=str(page.id),
                title=page.title,
                slug=page.slug,
                body=page.body_md[:800],
                kb_id=str(page.kb_id),
                label="相关 Wiki",
            )
        feed_notes()

    if data.web_search and web_results:
        # 给联网来源预留 3 个引用位，知识库结果最多保留 7 条。
        context_parts = context_parts[:7]
        citations = citations[: len(context_parts)]
        for item in web_results[:3]:
            add_web(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("snippet") or ""),
                content=str(item.get("content") or ""),
            )

    # 上下文与引用必须严格等长，否则模型可能引用到未提供的序号。
    context_parts = context_parts[:10]
    citations = citations[: len(context_parts)]

    # LLM 生成（页面级模型覆盖仅对本次请求生效；模型已在规划前解析）
    stage("generate", "start", "正在生成回答")

    system_prompt = (
        "你是 Kiwi 个人知识库助手。基于提供的 Wiki 页面与工作区笔记回答用户问题。\n"
        "规则：\n"
        "1. 综合 Wiki 的概念结构与笔记中的事实、数据、出处；笔记是用户整理后的最终内容，"
        "两者冲突时以笔记记录的出处为准，并明确指出冲突。\n"
        "2. 资料不足以回答时，明确说'知识库中未找到相关内容'，不要编造。\n"
        "3. 每个事实性结论都要在句末标注来源 [n]（n 为资料序号），可并列多个如 [1][3]；"
        "不要编造序号，也不要在正文中另列来源清单。\n"
        "4. 回答保持简洁，优先直接回应用户问题，再补充必要的背景。\n"
        "5. 标注「联网结果」的资料来自互联网，引用时同样使用 [n]；涉及网页时在"
        "对应结论后附上资料给出的原文链接，不要编造 URL。\n"
        "6. 资料中的「笔记内嵌附件」是用户上传文件的正文（可能被截断）；回答文件"
        "相关问题时，应依据其中的函数、参数与流程说明，而不是只复述文件名和大小。\n"
        + (
            f"对话上下文：用户当前消息「{query}」是对上一轮的追问，"
            f"已按补全后的问题「{context_query}」检索；回答时请延续上文主题，"
            "不要只按当前几个字作答。\n"
            if contextual
            else ""
        )
        + plan.prompt_context()
        + "\n资料：\n\n"
        + "\n\n---\n\n".join(context_parts)
        + ("\n\n（本次检索未命中任何资料，请如实告知用户。）" if not context_parts else "")
    )
    openai_msgs = [{"role": "system", "content": system_prompt}]
    for m in data.messages:
        if m.get("role") in ("user", "assistant"):
            openai_msgs.append({"role": m["role"], "content": str(m.get("content", ""))})

    return _PreparedChat(
        openai_msgs=openai_msgs,
        citations=citations,
        intent=intent,
        cfg=cfg,
        client=client,
        model_name=model_name,
        notices=notices,
    )


@router.post("/stream")
async def chat_stream(data: ChatRequest, session: AsyncSession = Depends(get_session)):
    """流式问答。返回 SSE 事件流。"""
    query = str(data.messages[-1].get("content", "")) if data.messages else ""
    if not query.strip():
        raise HTTPException(400, "问题不能为空")
    if is_disabled():
        raise HTTPException(
            409, "向量模型已关闭，问答检索不可用；请先在设置中启用向量模型。"
        )

    intent = route_intent(query) if data.intent in (None, "auto") else data.intent
    # 兼容旧客户端：raw 意图改由笔记承载（笔记是素材整理后的最终形态）。
    if intent == "raw":
        intent = "note"
    if intent not in ("wiki", "note"):
        raise HTTPException(400, "无效的检索意图")

    async def gen():
        from openai import APIConnectionError, APIError, APIStatusError

        def sse(evt_type: str, payload: dict) -> str:
            return f"event: {evt_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        def stage(name: str, status: str, message: str, detail: str = "") -> None:
            queue.put_nowait(
                (
                    "stage",
                    {
                        "stage": name,
                        "status": status,
                        "message": message,
                        "detail": detail,
                    },
                )
            )

        task = asyncio.create_task(_prepare_chat(session, data, query, intent, stage))
        try:
            # 检索期间持续把阶段事件推给前端；等待时发注释帧保持连接。
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    evt_type, payload = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield sse(evt_type, payload)
        finally:
            if not task.done():
                task.cancel()

        try:
            prepared = task.result()
        except HTTPException as exc:
            yield sse("error", {"message": str(exc.detail)})
            return
        except Exception:  # noqa: BLE001 —— 流已开始，只能通过 SSE 通知
            logger.exception("问答检索准备失败")
            yield sse("error", {"message": "检索资料时出现异常，请稍后重试。"})
            return

        # 非致命问题先通知前端，回答仍继续。
        for notice in prepared.notices:
            yield sse("notice", {"message": notice})
        yield sse(
            "citation",
            {
                "citations": [c.model_dump() for c in prepared.citations],
                "intent": prepared.intent,
            },
        )
        try:
            # 上游 503（Service is too busy）、429 与连接中断常是瞬时故障：
            # 在流开始前做两次短重试，并把重试状态反馈到「生成回答」步骤。
            stream = None
            for attempt in range(3):
                try:
                    stream = await prepared.client.chat.completions.create(
                        model=prepared.model_name,
                        messages=prepared.openai_msgs,
                        stream=True,
                        temperature=prepared.cfg.extra_params.get("temperature", 0.3),
                    )
                    break
                except (APIConnectionError, APIStatusError) as exc:
                    status = getattr(exc, "status_code", None)
                    retryable = isinstance(exc, APIConnectionError) or status in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                    if not retryable or attempt >= 2:
                        raise
                    yield sse(
                        "stage",
                        {
                            "stage": "generate",
                            "status": "active",
                            "message": f"模型服务繁忙，正在重试（{attempt + 1}/2）",
                        },
                    )
                    await asyncio.sleep(1.5 * (attempt + 1))
            if stream is None:  # pragma: no cover —— 循环必然 break 或抛错
                raise RuntimeError("模型未返回流式响应")
            async for chunk in stream:
                # 部分 OpenAI 兼容服务（如 DeepSeek）会在末尾追加仅含 usage、
                # choices 为空的分片；直接取 choices[0] 会抛 IndexError。
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield sse("chunk", {"text": delta.content})
            yield sse("stage", {"stage": "generate", "status": "done", "message": "回答生成完成"})
            yield sse("done", {"ok": True})
        except (APIError, APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            if status in (429, 503):
                message = (
                    f"模型服务繁忙（HTTP {status}），已自动重试仍失败，"
                    "请稍后重试或切换模型配置。"
                )
            elif status:
                message = f"LLM 调用失败（HTTP {status}）：{e}"
            else:
                message = f"LLM 调用失败：{e}"
            yield sse("error", {"message": message})
        except Exception:  # noqa: BLE001 —— 流已开始，只能通过 SSE 通知客户端
            logger.exception("问答流式生成异常")
            yield sse("error", {"message": "生成过程中出现异常，请稍后重试。"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
