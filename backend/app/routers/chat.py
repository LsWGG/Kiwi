"""流式问答路由：检索增强 → LLM 流式生成 → SSE 事件。

检索范围为 Wiki 页面 + 工作区笔记；笔记是素材整理后的最终形态，
因此不再检索 raw_chunks。事件：chunk(citation 内嵌) / citation / done /
error / keepalive。引用严格限定在用户检索范围内（kb_id 边界由检索层强制）。
"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, LLMConfig, Note, WikiLink, WikiPage
from app.db.session import get_session
from app.schemas.chat import ChatRequest, Citation, SearchScope
from app.services.llm_factory import LLMCrypto, llm_factory
from app.services.note_indexer import ensure_notes_indexed
from app.services.retrieval import route_intent, search

logger = logging.getLogger("kiwi.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])


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


@router.post("/stream")
async def chat_stream(data: ChatRequest, session: AsyncSession = Depends(get_session)):
    """流式问答。返回 SSE 事件流。"""
    kb_ids = await _resolve_scope(session, data.scope)
    query = str(data.messages[-1].get("content", "")) if data.messages else ""
    if not query.strip():
        raise HTTPException(400, "问题不能为空")

    intent = route_intent(query) if data.intent in (None, "auto") else data.intent
    # 兼容旧客户端：raw 意图改由笔记承载（笔记是素材整理后的最终形态）。
    if intent == "raw":
        intent = "note"
    if intent not in ("wiki", "note"):
        raise HTTPException(400, "无效的检索意图")
    # 意图路由：Wiki 优先（概念/综合）或笔记优先（精确定位、事实核验）
    wiki_limit = 8 if intent == "wiki" else 4
    # 多取一些笔记分块：数据表 / 长文档的相邻行可能排在稍后的名次，
    # 只取 8 条会漏掉尾部记录；合并后仍按笔记去重并受上下文预算约束。
    note_limit = 16
    wiki_hits = await search(
        session, query, kb_ids, limit=wiki_limit, collection="wiki"
    )
    try:
        # 问答前同步刚编辑过的笔记，避免答案落后于用户的最新整理。
        await ensure_notes_indexed(kb_ids)
    except Exception:  # noqa: BLE001 —— 索引失败不影响 Wiki 检索
        logger.warning("笔记索引同步失败，继续检索已有向量", exc_info=True)
    note_hits = await search(
        session, query, kb_ids, limit=note_limit, collection="note"
    )
    kb_names = await _kb_names(session, kb_ids)

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
            )
        )
        # 数据表的行内容可能分布在多个分块中，给笔记更宽的上下文预算。
        context_parts.append(
            f"[{len(citations)}] ({prefix}·{kind_label}) {title}\n{(text or '')[:2000]}"
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
            and all(text != existing for _, existing in group["chunks"])
            and len(group["chunks"]) < 4
        ):
            group["chunks"].append((int(payload.get("chunk_index") or 0), text))

    # 以数据库为准过滤已删除 / 回收站笔记，并取最新标题（向量 payload 可能滞后）。
    note_meta: dict[str, tuple[str, str]] = {}
    note_ids: list[uuid.UUID] = []
    for note_id in note_groups:
        try:
            note_ids.append(uuid.UUID(note_id))
        except ValueError:
            continue
    if note_ids:
        rows = (
            await session.execute(
                select(Note.id, Note.title, Note.kind).where(
                    Note.id.in_(note_ids),
                    Note.kb_id.in_(kb_ids),
                    Note.status == "active",
                )
            )
        ).all()
        note_meta = {str(row.id): (row.title, row.kind) for row in rows}

    note_entries = [
        (note_id, group)
        for note_id, group in note_groups.items()
        if note_id in note_meta and group["chunks"]
    ]

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
            title, kind = note_meta[note_id]
            add_note(
                note_id=note_id,
                title=title or group["title"] or "未命名笔记",
                kind=kind or group["kind"],
                # 按原始分块顺序拼接，避免打乱表格行的语义。
                text="\n\n".join(text for _, text in sorted(group["chunks"])),
                kb_id=group["kb_id"],
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

    # 上下文与引用必须严格等长，否则模型可能引用到未提供的序号。
    context_parts = context_parts[:10]
    citations = citations[: len(context_parts)]

    # LLM 生成（页面级模型覆盖仅对本次请求生效）
    # 模型级联：页面级 > 单库绑定 > 全局默认；多库 / 全局不做任意单库绑定推断
    bound_kb_id = kb_ids[0] if data.scope.scope == "kb" and kb_ids else None
    cfg, api_key = await resolve_llm(session, bound_kb_id, data.llm_config_id)
    model_name = (data.model_override or "").strip() or cfg.model_name
    client = llm_factory.get_client(cfg.base_url, api_key or None, model_name)

    system_prompt = (
        "你是 Kiwi 个人知识库助手。基于提供的 Wiki 页面与工作区笔记回答用户问题。\n"
        "规则：\n"
        "1. 综合 Wiki 的概念结构与笔记中的事实、数据、出处；笔记是用户整理后的最终内容，"
        "两者冲突时以笔记记录的出处为准，并明确指出冲突。\n"
        "2. 资料不足以回答时，明确说'知识库中未找到相关内容'，不要编造。\n"
        "3. 每个事实性结论都要在句末标注来源 [n]（n 为资料序号），可并列多个如 [1][3]；"
        "不要编造序号，也不要在正文中另列来源清单。\n"
        "4. 回答保持简洁，优先直接回应用户问题，再补充必要的背景。\n"
        "资料：\n\n"
        + "\n\n---\n\n".join(context_parts)
        + ("\n\n（本次检索未命中任何资料，请如实告知用户。）" if not context_parts else "")
    )
    openai_msgs = [{"role": "system", "content": system_prompt}]
    for m in data.messages:
        if m.get("role") in ("user", "assistant"):
            openai_msgs.append({"role": m["role"], "content": str(m.get("content", ""))})

    async def gen():
        from openai import APIConnectionError, APIError

        def sse(evt_type: str, payload: dict) -> str:
            return f"event: {evt_type}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        # 先发引用
        yield sse("citation", {"citations": [c.model_dump() for c in citations], "intent": intent})
        try:
            stream = await client.chat.completions.create(
                model=model_name,
                messages=openai_msgs,
                stream=True,
                temperature=cfg.extra_params.get("temperature", 0.3),
            )
            async for chunk in stream:
                # 部分 OpenAI 兼容服务（如 DeepSeek）会在末尾追加仅含 usage、
                # choices 为空的分片；直接取 choices[0] 会抛 IndexError，
                # 导致流在最后一段被中断且客户端收不到 done 事件。
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield sse("chunk", {"text": delta.content})
            yield sse("done", {"ok": True})
        except (APIError, APIConnectionError) as e:
            yield sse("error", {"message": f"LLM 调用失败：{e}"})
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
