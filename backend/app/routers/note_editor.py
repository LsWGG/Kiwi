"""笔记编辑器增强路由：AI 写作助手 + Word 导出。"""

import asyncio
import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note
from app.db.session import get_session
from app.routers.chat import resolve_llm
from app.schemas.note import NoteAssistIn, NoteAssistOut, NoteAssistReference
from app.services.docx_export import markdown_to_docx, resolve_note_mentions
from app.services.llm_factory import llm_factory
from app.services.note_lock import token_is_valid
from app.services.retrieval import hyrid_search

router = APIRouter(prefix="/api/notes", tags=["note-editor"])

SYSTEM_PROMPT = (
    "你是 Kiwi 笔记里的写作助手。"
    "只输出 Markdown 正文：不要解释你的处理过程，不要用代码围栏包裹整段结果。"
    "保持原文语言、语气与信息密度；除非用户要求，不要杜撰事实。"
)

ACTION_PROMPTS = {
    "continue": "接着给定内容自然续写，不要重复已有句子，直接给出续写部分。",
    "polish": "润色给定内容：修正语病、提升清晰度与可读性，保留原意和全部信息。",
    "shorten": "缩写给定内容：保留关键事实、结论与数据，删除冗余修饰，压缩到原文的 40%–60%，只输出缩写结果。",
    "summarize": "把给定内容提炼为 3-6 条要点，使用 Markdown 无序列表，每条一句话。",
    "translate": "翻译给定内容：原文是中文就译为英文，否则译为中文；只输出译文。",
    "explain": "",
    "custom": "",
}

EXPLAIN_SYSTEM_PROMPT = (
    "你是 Kiwi 知识库里的解释助手。只依据用户提供的参考片段解释选中内容，"
    "不要引入片段之外的事实。在引用处用 [1]、[2] 这样的编号标注来源。"
    "参考片段不足以回答时，明确说明「当前知识库中没有足够的信息」。"
    "只输出 Markdown 正文，不要解释你的处理过程。"
)

MAX_MODEL_CHARS = 12000
MAX_EXPLAIN_QUOTE = 600
EXPLAIN_SCORE_FLOOR = 0.25


async def _get_note(session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID) -> Note:
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id:
        raise HTTPException(404, "笔记不存在")
    return note


async def _explain_references(
    session: AsyncSession, kb_id: uuid.UUID, query: str
) -> list[NoteAssistReference]:
    """按语义检索当前知识库，收集「基于知识库解释」的引用片段（Wiki 优先）。"""
    query = query.strip()[:2000]
    if not query:
        return []
    try:
        hits = await hyrid_search(session, query, [kb_id], limit=4)
    except Exception as e:  # noqa: BLE001 - 模型加载/网络异常统一提示
        raise HTTPException(502, f"知识库检索失败：{e}") from e
    refs: list[NoteAssistReference] = []
    seen_wiki: set[str] = set()
    for hit in hits.get("wiki", []):
        payload = hit.get("payload") or {}
        page_id = str(payload.get("page_id") or "")
        score = float(hit.get("score") or 0.0)
        if not page_id or page_id in seen_wiki or score < EXPLAIN_SCORE_FLOOR:
            continue
        seen_wiki.add(page_id)
        refs.append(
            NoteAssistReference(
                kind="wiki",
                title=str(payload.get("title") or "Wiki 页面"),
                quote=str(payload.get("body_head") or "")[:MAX_EXPLAIN_QUOTE],
                score=round(score, 4),
                wiki_page_id=uuid.UUID(page_id),
            )
        )
        if len(refs) >= 4:
            break

    seen_raw: set[tuple[str, int]] = set()
    raw_refs: list[NoteAssistReference] = []
    for hit in hits.get("raw", []):
        payload = hit.get("payload") or {}
        source_id = str(payload.get("source_id") or "")
        chunk_index = int(payload.get("chunk_index") or 0)
        score = float(hit.get("score") or 0.0)
        key = (source_id, chunk_index)
        if not source_id or key in seen_raw or score < EXPLAIN_SCORE_FLOOR:
            continue
        seen_raw.add(key)
        raw_refs.append(
            NoteAssistReference(
                kind="source",
                title=str(payload.get("source_title") or payload.get("title") or "素材"),
                quote=str(payload.get("text") or "")[:MAX_EXPLAIN_QUOTE],
                score=round(score, 4),
                source_id=uuid.UUID(source_id),
            )
        )
        if len(raw_refs) >= 4:
            break
    return refs + raw_refs


@router.post("/{note_id}/assist", response_model=NoteAssistOut)
async def assist(
    note_id: uuid.UUID,
    data: NoteAssistIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """编辑器 AI 动作：续写 / 润色 / 总结 / 翻译 / 基于知识库解释 / 自定义指令。"""
    note = await _get_note(session, kb_id, note_id)

    selection = (data.selection or "").strip()
    context = (data.context or "").strip()
    instruction = (data.instruction or "").strip()
    if data.action == "custom" and not instruction:
        raise HTTPException(400, "请输入自定义指令")
    if not selection and not context:
        raise HTTPException(400, "文档还是空的，先写一点内容再让 AI 处理吧")

    references: list[NoteAssistReference] = []
    system_prompt = SYSTEM_PROMPT
    if data.action == "explain":
        references = await _explain_references(
            session,
            kb_id,
            selection or context[:800] or note.title or "",
        )
        if not references:
            raise HTTPException(
                409,
                "当前知识库中没有找到可引用的内容，请先导入资料或编译 Wiki 后再试",
            )
        system_prompt = EXPLAIN_SYSTEM_PROMPT

    cfg, api_key = await resolve_llm(session, kb_id, None)
    if not cfg.model_name:
        raise HTTPException(400, "该模型连接未设置模型名称，请先在设置中补全")

    if data.action == "custom":
        task = instruction
    else:
        task = ACTION_PROMPTS[data.action]
    if data.action == "explain":
        reference_block = "\n\n".join(
            f"[{i + 1}] {ref.title}\n{ref.quote}" for i, ref in enumerate(references)
        )
        user_prompt = (
            f"解释以下内容：\n{selection or context[:2000]}\n\n"
            f"## 文档上下文\n{context[:4000] or '（空）'}\n\n"
            f"## 参考片段\n{reference_block}"
        )
    else:
        user_prompt = (
            f"{task}\n\n"
            f"## 选中文本\n{selection or '（无选中文本，以下方文档上下文为准）'}\n\n"
            f"## 文档上下文\n{(context or '（空）')[:MAX_MODEL_CHARS]}"
        )

    client = llm_factory.get_client(cfg.base_url, api_key or None, cfg.model_name)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=cfg.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4 if data.action == "explain" else 0.5,
                max_tokens=1500,
                stream=False,
            ),
            timeout=120,
        )
    except asyncio.TimeoutError as e:
        raise HTTPException(504, "AI 生成超时，请稍后重试") from e
    except Exception as e:  # noqa: BLE001 - 第三方客户端异常统一转为 502
        raise HTTPException(502, f"AI 生成失败：{e}") from e

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise HTTPException(502, "AI 没有返回内容，请重试")
    return NoteAssistOut(result=content, references=references)


_NOTE_ID_RE = re.compile(r"kiwi://note/([0-9a-fA-F-]{36})")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}")


async def _mention_titles(
    session: AsyncSession, kb_id: uuid.UUID, markdown: str
) -> dict[str, str]:
    """收集正文里提及的笔记标题，供 Word 导出替换 UUID。"""
    raw_ids = set(_NOTE_ID_RE.findall(markdown))
    raw_ids.update(
        _UUID_RE.findall(markdown) if "@" in markdown else [],
    )
    note_ids: list[uuid.UUID] = []
    for raw in raw_ids:
        try:
            note_ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not note_ids:
        return {}
    rows = await session.execute(
        select(Note.id, Note.title).where(Note.kb_id == kb_id, Note.id.in_(note_ids))
    )
    return {str(note_id): title for note_id, title in rows if title}


@router.get("/{note_id}/export/docx")
async def export_docx(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """把笔记正文转换为 Word 文档下载。"""
    note = await _get_note(session, kb_id, note_id)
    if note.is_locked and not token_is_valid(note, x_note_token):
        raise HTTPException(403, "笔记已上锁，请先输入密码解锁后再导出")
    props = note.props_json or {}
    body_md = note.body_md or ""
    titles = await _mention_titles(session, kb_id, body_md)
    if titles:
        body_md = resolve_note_mentions(body_md, titles)
    buffer = markdown_to_docx(
        note.title or "无标题文档",
        body_md,
        props.get("docx_prefs") if isinstance(props.get("docx_prefs"), dict) else None,
        props.get("paragraph_formats")
        if isinstance(props.get("paragraph_formats"), list)
        else None,
        props.get("text_formats")
        if isinstance(props.get("text_formats"), list)
        else None,
    )
    safe_title = (note.title or "note").replace("/", "_").replace("\\", "_").strip() or "note"
    filename = quote(f"{safe_title}.docx")
    return Response(
        content=buffer.getvalue(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
