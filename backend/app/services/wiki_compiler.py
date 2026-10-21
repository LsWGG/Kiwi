"""LLM Wiki 编译流水线（阶段一基础版）。

parse → chunk → embed_raw → store → retrieve_related_pages → compile_wiki → index_wiki → finalize

Schema 以提示词模板形式内嵌，预留文件化接口。
尊重 human_edited=true 的页面：不被编译覆盖，仅标记源漂移。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, WikiPage
from app.db.session import async_session_factory
from app.event_hub import hub
from app.repositories import WikiPageRepo
from app.services import qdrant_store
from app.services.embedder import embed_one_async, embed_texts_async
from app.services.llm_factory import LLMCrypto, LLMFactory
from app.services.wiki_links import WIKI_LINK_RE, strip_code
from app.services.wiki_schema import load_schema

logger = logging.getLogger(__name__)

ALLOWED_PAGE_TYPES = {"entity", "concept", "summary", "synthesis"}

COMPILE_PROMPT = """你是一个知识库编译引擎。给定一篇新材料的文本块、当前知识库已有的 Wiki 页面清单，以及本库的 Wiki Schema，请产出对 Wiki 的增量更新。

下面这份 Schema 由用户维护，是必须遵守的结构化规范（页面类型与模板、slug 与 wikilink 规范、质量标准、ingest 指令）：
<wiki_schema>
{schema}
</wiki_schema>

当前知识库已有页面（标题 + slug，可能为空）：
{existing_titles}

与新材料语义相关的现有页面（供判断更新还是新建；节选正文）：
{related_pages}

要求：
1. 严格按 Schema 的页面类型、模板、slug 与 wikilink 规范产出页面。
2. 若文本涉及现有页面，优先 update 该页面（patch 写增量补充段，不要重写整页）。
3. 若文本引入新主题，create 新页面（slug 唯一，小写短横线，优先复用 Schema 中的中文 slug 约定）。
4. 页面用 Markdown 编写；每个新页至少按 Schema 要求建立交叉引用（[[slug]] 形式）。
5. 只在材料明确支持的内容范围内写作，不编造事实；涉及法规/数据必须按 Schema 标注来源；矛盾按 Schema 的矛盾标记格式记录。
6. 只输出 JSON，不输出解释文字。格式：{{"create": [{{"slug": "...", "title": "...", "page_type": "entity|concept|summary|synthesis", "body_md": "..."}}], "update": [{{"slug": "...", "patch": "..."}}]}}。
"""


def _validate_compile_output(data: dict) -> dict:
    """校验 / 清洗 LLM 输出，保证下游只处理契约内的结构。"""
    if not isinstance(data, dict):
        raise CompileError("编译输出应为 JSON 对象（包含 create / update）")

    def _as_list(key: str) -> list:
        value = data.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list):
            raise CompileError(f"编译输出字段 {key} 应为数组")
        return value

    create: list[dict] = []
    for item in _as_list("create"):
        if not isinstance(item, dict):
            logger.warning("跳过非对象 create 项：%r", item)
            continue
        slug = str(item.get("slug") or item.get("title") or "").strip()[:120]
        if not slug:
            continue
        title = str(item.get("title") or slug).strip()[:300] or slug
        page_type = str(item.get("page_type") or "entity").strip().lower()
        if page_type not in ALLOWED_PAGE_TYPES:
            page_type = "entity"
        body = item.get("body_md", item.get("body", ""))
        body = str(body or "")[:60_000]
        create.append(
            {"slug": slug, "title": title, "page_type": page_type, "body_md": body}
        )

    update: list[dict] = []
    for item in _as_list("update"):
        if not isinstance(item, dict):
            logger.warning("跳过非对象 update 项：%r", item)
            continue
        slug = str(item.get("slug") or "").strip()[:120]
        title = str(item.get("title") or "").strip()[:300]
        patch = str(item.get("patch") or item.get("body_md") or "")[:60_000]
        if not (slug or title) or not patch.strip():
            continue
        update.append({"slug": slug, "title": title, "patch": patch})

    return {"create": create, "update": update}


class CompileError(Exception):
    pass


async def _job_heartbeat(job_id: uuid.UUID, stop: asyncio.Event) -> None:
    """LLM 生成期间定期刷新任务的 updated_at。

    编译阶段一次 LLM 调用可能持续数分钟，期间没有进度落库；心跳让前端轮询
    能持续看到「最近更新 / 用时」变化，而不是误以为任务卡死。
    """
    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.db.models import IngestJob

    while not stop.is_set():
        try:
            async with async_session_factory() as db:
                await db.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job_id)
                    .values(updated_at=datetime.now(timezone.utc))
                )
                await db.commit()
        except Exception:  # noqa: BLE001 —— 心跳失败不影响编译本身
            logger.debug("刷新编译任务心跳失败", exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


async def _resolve_llm_config(db: AsyncSession, kb: KnowledgeBase) -> tuple[dict, str]:
    """按级联解析目标 LLM：知识库默认 > 系统默认。
    返回 ({base_url, model_name, extra_params}, decrypted_api_key)。"""
    from sqlalchemy import select

    from app.db.models import LLMConfig

    cfg: LLMConfig | None = None
    if kb.llm_config_id:
        cfg = await db.get(LLMConfig, kb.llm_config_id)
    if cfg is None:
        rows = await db.execute(select(LLMConfig).where(LLMConfig.is_default.is_(True)))
        cfg = rows.scalars().first()
    if cfg is None:
        raise CompileError("未配置任何大模型连接，请先在设置中添加并设为默认。")
    api_key = ""
    if cfg.encrypted_api_key:
        api_key = LLMCrypto.decrypt(cfg.encrypted_api_key)
    return cfg, api_key


async def _existing_wiki_titles(db: AsyncSession, kb_id: uuid.UUID) -> list[tuple[str, str]]:
    from sqlalchemy import select

    rows = await db.execute(
        select(WikiPage.title, WikiPage.slug).where(WikiPage.kb_id == kb_id)
    )
    return list(rows.all())


async def _related_wiki_pages(
    db: AsyncSession, kb: KnowledgeBase, chunks: list[dict]
) -> list[WikiPage]:
    """语义检索与新素材相关的现有 Wiki 页（供 LLM 判断更新 / 新建）。

    这是 README 中 compile 流程的 retrieve_related_pages 步骤；检索失败不应
    阻断编译，降级为仅依据标题清单判断。
    """
    query = "\n".join(str(c.get("content") or "")[:800] for c in chunks[:3]).strip()[:2000]
    if not query:
        return []
    try:
        vector = await embed_one_async(query, kb.embedding_model)
        hits = await asyncio.to_thread(
            qdrant_store.search,
            qdrant_store.wiki_collection(kb.embedding_model),
            vector,
            kb.id,
            5,
            0.2,
        )
    except Exception as e:  # noqa: BLE001 —— 向量服务故障时继续编译
        logger.warning("相关 Wiki 页检索失败（继续编译）：%s", e)
        return []

    page_ids: list[uuid.UUID] = []
    for hit in hits:
        try:
            page_ids.append(uuid.UUID(str(hit.get("payload", {}).get("page_id"))))
        except (ValueError, TypeError):
            continue
    if not page_ids:
        return []
    rows = await db.execute(
        select(WikiPage).where(
            WikiPage.kb_id == kb.id, WikiPage.id.in_(page_ids)
        )
    )
    by_id = {p.id: p for p in rows.scalars().all()}
    return [by_id[i] for i in page_ids if i in by_id]


def _parse_llm_json(raw: str) -> dict:
    """解析 LLM 输出的 JSON（容忍 markdown 代码块包裹）。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # 去掉可能的 json 前缀
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    import json

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise CompileError(f"编译输出非合法 JSON：{e}，原始：{raw[:300]}") from e


async def _slugify(title: str) -> str:
    import re

    slug = re.sub(r"[^\w一-鿿-]+", "-", title.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:120]
    return slug or "page"


async def _rebuild_wiki_links(db: AsyncSession, kb_id: uuid.UUID) -> None:
    """扫描本库全部 wiki 页的 [[slug]] 链接，重建 wiki_links 边。

    阶段一简化：链接以 slug 匹配（编译产物统一用 [[小写短横线]]）。
    human_edited 页若含手写 [[标题]]，仅匹配不到时忽略。
    """
    from sqlalchemy import delete, select

    from app.db.models import WikiLink, WikiPage

    pages = list(
        (await db.execute(select(WikiPage).where(WikiPage.kb_id == kb_id))).scalars().all()
    )
    # 归一化 -/_，使 [[pg-dump]] 能命中 slug pg_dump（_slugify 保留 _）
    def _norm(s: str) -> str:
        return s.strip().lower().replace("_", "-")

    slug_to_id: dict[str, uuid.UUID] = {}
    for p in pages:
        slug_to_id[p.slug] = p.id
        slug_to_id.setdefault(_norm(p.slug), p.id)

    # 清空本库旧边（编译会全量重建）
    page_ids = [p.id for p in pages]
    if page_ids:
        await db.execute(
            delete(WikiLink).where(
                WikiLink.from_page_id.in_(page_ids) | WikiLink.to_page_id.in_(page_ids)
            )
        )

    # 引用边；同一行出现「矛盾 / ⚠️」标记时升级为矛盾边（README 10.2）。
    refs: dict[uuid.UUID, set[uuid.UUID]] = {p.id: set() for p in pages}
    conflicts: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for p in pages:
        for line in strip_code(p.body_md or "").splitlines():
            link_slugs = WIKI_LINK_RE.findall(line)
            if not link_slugs:
                continue
            is_conflict = "矛盾" in line or "⚠" in line or "冲突" in line
            for target_slug in link_slugs:
                target_id = slug_to_id.get(_norm(target_slug))
                if target_id is None or target_id == p.id:
                    continue
                refs[p.id].add(target_id)
                if is_conflict:
                    conflicts.add((p.id, target_id))

    for from_id, targets in refs.items():
        for to_id in targets:
            db.add(
                WikiLink(
                    from_page_id=from_id,
                    to_page_id=to_id,
                    link_type="contradiction"
                    if (from_id, to_id) in conflicts
                    else "reference",
                )
            )

    # 相关边：共同引用（>=2 个共同目标）或共享 frontmatter 标签。
    # 只补充没有直接引用的页面对，避免把引用图变成稠密图。
    related: set[frozenset[uuid.UUID]] = set()
    tag_sets = {
        p.id: {str(t).strip().lower() for t in (p.frontmatter_json or {}).get("tags") or [] if str(t).strip()}
        for p in pages
    }
    for i, a in enumerate(pages):
        for b in pages[i + 1 :]:
            if b.id in refs[a.id] or a.id in refs[b.id]:
                continue
            shared_targets = refs[a.id] & refs[b.id]
            shared_tags = tag_sets[a.id] & tag_sets[b.id]
            if len(shared_targets) >= 2 or shared_tags:
                related.add(frozenset((a.id, b.id)))
    for pair in related:
        first, second = sorted(pair, key=str)
        db.add(
            WikiLink(from_page_id=first, to_page_id=second, link_type="related")
        )
    await db.flush()


async def compile_source(
    job_id: uuid.UUID,
    source_id: uuid.UUID,
    kb: KnowledgeBase,
    chunks: list[dict],
) -> dict:
    """编译单个素材。返回 {created, updated, touched_page_ids}。"""

    async def emit(e_type: str, payload: dict) -> None:
        await hub.publish(str(job_id), {"type": e_type, "payload": payload})

    await emit("compile_start", {"source_id": str(source_id)})

    # 已有标题 + 语义相关的现有页面
    async with async_session_factory() as db:
        existing = await _existing_wiki_titles(db, kb.id)
        related = await _related_wiki_pages(db, kb, chunks)

    schema_text, _ = load_schema(kb.id)

    llm = LLMFactory()
    async with async_session_factory() as resolve_db:
        cfg, api_key = await _resolve_llm_config(resolve_db, kb)
    client = llm.get_client(cfg.base_url, api_key or None, cfg.model_name)

    # 组装 prompt
    material = "\n\n---\n\n".join(f"[{c['title']}]\n{c['content'][:1200]}" for c in chunks)[:15000]
    related_text = "\n\n---\n\n".join(
        f"[{p.title}]（slug: {p.slug}）\n{(p.body_md or '')[:1200]}" for p in related
    )
    prompt = COMPILE_PROMPT.format(
        schema=schema_text,
        existing_titles=", ".join(f"{t}（slug: {s}）" for t, s in existing) or "（空）",
        related_pages=related_text or "（无相关页面）",
    )
    messages = [
        {"role": "system", "content": "你是一个严谨的知识库编译引擎，只输出 JSON。"},
        {"role": "user", "content": f"{prompt}\n\n新材料内容：\n{material}"},
    ]

    from openai import APIError

    from app.services.metrics import llm_call

    heartbeat_stop = asyncio.Event()
    heartbeat = asyncio.create_task(_job_heartbeat(job_id, heartbeat_stop))
    try:
        async with llm_call(cfg.model_name):
            resp = await client.chat.completions.create(
                model=cfg.model_name,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        raw = resp.choices[0].message.content or ""
    except APIError as e:
        raise CompileError(f"LLM 调用失败：{e}") from e
    finally:
        heartbeat_stop.set()
        await heartbeat

    data = _validate_compile_output(_parse_llm_json(raw))
    created_ids: list[uuid.UUID] = []
    updated_ids: list[uuid.UUID] = []

    import datetime as _dt

    async with async_session_factory() as db:
        repo = WikiPageRepo(db)
        by_title = {t.strip().lower(): s for t, s in existing}
        for page in data.get("create", []):
            raw_slug = str(page.get("slug") or page.get("title") or "")
            slug = await _slugify(raw_slug)
            existing_page = await repo.get_by_slug(kb.id, slug)
            # 人工编辑页不被自动编译覆盖（README：human_edited 保护）
            if existing_page and existing_page.human_edited:
                continue
            prev_fm = (existing_page.frontmatter_json or {}) if existing_page else {}
            source_ids = list(
                dict.fromkeys(list(prev_fm.get("sources") or []) + [str(source_id)])
            )
            obj = await repo.upsert(
                kb.id,
                slug,
                title=page.get("title", slug),
                page_type=page.get("page_type", "entity"),
                body_md=page.get("body_md", ""),
                frontmatter_json={
                    **prev_fm,
                    "type": page.get("page_type", "entity"),
                    "sources": source_ids,
                    "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                },
                compiled_from_source_ids=list(
                    dict.fromkeys(
                        list(
                            (existing_page.compiled_from_source_ids if existing_page else [])
                            or []
                        )
                        + [str(source_id)]
                    )
                ),
            )
            created_ids.append(obj.id)
            await emit("compile_page", {"slug": slug, "page_type": page.get("page_type")})
        for page in data.get("update", []):
            raw_slug = str(page.get("slug") or "")
            if not raw_slug:
                # 模型只给标题时，用现有标题→slug 映射兜底
                raw_slug = by_title.get(str(page.get("title") or "").strip().lower(), "")
            slug = await _slugify(raw_slug) if raw_slug else ""
            obj = await repo.get_by_slug(kb.id, slug) if slug else None
            if obj is None:
                logger.warning("编译更新目标未找到：%s", page)
            if obj and not obj.human_edited:
                # 简单 patch 策略：追加"新增段落"
                obj.body_md = obj.body_md + "\n\n> 增量更新\n\n" + page.get("patch", "")
                obj.compiled_from_source_ids = list(
                    dict.fromkeys(obj.compiled_from_source_ids + [str(source_id)])
                )
                fm = dict(obj.frontmatter_json or {})
                fm["type"] = obj.page_type
                fm["sources"] = list(obj.compiled_from_source_ids)
                fm["updated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
                obj.frontmatter_json = fm
                obj.version += 1
                updated_ids.append(obj.id)
                await emit("compile_page", {"slug": slug, "patch": True})
        await db.commit()

        # 增量索引：只重新向量化本次创建 / 更新的页面
        touched_ids = list(dict.fromkeys(created_ids + updated_ids))
        pages = (
            list(
                (
                    await db.execute(
                        select(WikiPage).where(WikiPage.id.in_(touched_ids))
                    )
                )
                .scalars()
                .all()
            )
            if touched_ids
            else []
        )

    if pages:
        texts = [f"{p.title}\n{p.body_md[:2000]}" for p in pages]
        vecs = await embed_texts_async(texts, kb.embedding_model)
        # 先清除旧向量，避免同一页面在 collection 中产生重复点
        for p in pages:
            qdrant_store.delete_wiki_page(kb.id, p.id, kb.embedding_model)
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
            for p, v in zip(pages, vecs)
        ]
        qdrant_store.upsert_wiki_pages(kb.id, points, kb.embedding_model)

    # 重建页面间引用边（图谱数据）
    async with async_session_factory() as db:
        await _rebuild_wiki_links(db, kb.id)
        # 重建 Wiki 后页面 id 会变化：按 slug 把学习题目 / 复习 / 知识点重新挂回页面。
        if pages:
            from sqlalchemy import update

            from app.db.models import LearningTopic, StudyQuestion, StudyReview

            for page in pages:
                await db.execute(
                    update(LearningTopic)
                    .where(
                        LearningTopic.kb_id == kb.id,
                        LearningTopic.slug == page.slug,
                        LearningTopic.wiki_page_id.is_(None),
                    )
                    .values(wiki_page_id=page.id)
                )
                await db.execute(
                    update(StudyReview)
                    .where(
                        StudyReview.kb_id == kb.id,
                        StudyReview.slug == page.slug,
                        StudyReview.wiki_page_id.is_(None),
                    )
                    .values(wiki_page_id=page.id)
                )
                await db.execute(
                    update(StudyQuestion)
                    .where(
                        StudyQuestion.kb_id == kb.id,
                        StudyQuestion.topic_slug == page.slug,
                        StudyQuestion.wiki_page_id.is_(None),
                    )
                    .values(wiki_page_id=page.id)
                )
        await db.commit()

    await emit(
        "compile_done",
        {
            "created": [str(i) for i in created_ids],
            "updated": [str(i) for i in updated_ids],
        },
    )
    return {
        "created": created_ids,
        "updated": updated_ids,
        "touched_page_ids": [str(i) for i in created_ids + updated_ids],
    }
