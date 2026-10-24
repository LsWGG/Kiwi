"""笔记整理建议：本地标签匹配 + 可选大模型标签推荐。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NoteTag
from app.db.session import get_session
from app.routers.chat import resolve_llm
from app.routers.notes_shared import _get_note
from app.schemas.note import NoteTagSuggestion, NoteTagSuggestionsOut
from app.services.llm_factory import llm_factory
from app.services.note_lock import note_body, token_is_valid

router = APIRouter()

MAX_BODY_CHARS = 4000
MAX_TAG_SUGGESTIONS = 10

TAG_SYSTEM_PROMPT = (
    "你是笔记整理助手。根据标题、正文与已有标签为笔记推荐标签。"
    "只输出 JSON 字符串数组，不要输出解释、Markdown 代码围栏或其它内容。"
)


async def _local_tag_suggestions(
    session: AsyncSession, kb_id: uuid.UUID, note, body: str
) -> list[NoteTagSuggestion]:
    """匹配正文里出现、但尚未挂到笔记上的已有标签（高精度、无需模型）。"""
    attached = {tag.name for tag in note.tags}
    names = (
        await session.execute(
            select(NoteTag.name).where(NoteTag.kb_id == kb_id).order_by(NoteTag.name)
        )
    ).scalars().all()
    title = (note.title or "").lower()
    text = (body or "").lower()
    suggestions: list[NoteTagSuggestion] = []
    for raw_name in names:
        name = (raw_name or "").strip()
        if not name or name in attached:
            continue
        leaf = name.rsplit("/", 1)[-1].strip()
        evidence = ""
        for candidate in dict.fromkeys((name, leaf)):
            if len(candidate) < 2:
                continue
            needle = candidate.lower()
            if needle in title:
                evidence = f"标题包含「{candidate}」"
                break
            if needle in text:
                evidence = f"正文提到「{candidate}」"
                break
        if evidence:
            suggestions.append(
                NoteTagSuggestion(name=name, source="existing", evidence=evidence)
            )
    # 短标签通常更泛化，排在前面；最多返回 8 个，避免面板过长。
    suggestions.sort(key=lambda item: (len(item.name), item.name))
    return suggestions[:8]


def parse_tag_array(raw: str) -> list[str]:
    """从模型输出里提取 JSON 字符串数组；容忍代码围栏与前后解释。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        name = item.strip().lstrip("#").strip()
        key = name.lower()
        if not name or len(name) > 30 or key in seen:
            continue
        seen.add(key)
        tags.append(name)
    return tags


async def _ai_tag_suggestions(
    session: AsyncSession, kb_id: uuid.UUID, note, body: str
) -> list[str]:
    cfg, api_key = await resolve_llm(session, kb_id, None)
    if not cfg.model_name:
        raise RuntimeError("该模型连接未设置模型名称，请先在设置中补全")
    existing = (
        await session.execute(
            select(NoteTag.name)
            .where(NoteTag.kb_id == kb_id)
            .order_by(NoteTag.name)
            .limit(80)
        )
    ).scalars().all()
    prompt = (
        "为下面这篇笔记推荐 3-5 个标签。\n"
        "要求：优先复用「已有标签」；确有必要时才新增 2-8 个字的简短标签；"
        "标签要概括主题，不要人名、日期或无意义词。\n"
        '只输出 JSON 字符串数组，例如 ["性能优化","前端"]。\n\n'
        f"## 标题\n{(note.title or '未命名笔记')[:200]}\n\n"
        f"## 已有标签\n{'、'.join(existing) or '（无）'}\n\n"
        f"## 正文\n{(body or '')[:MAX_BODY_CHARS]}"
    )
    client = llm_factory.get_client(cfg.base_url, api_key or None, cfg.model_name)
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=cfg.model_name,
            messages=[
                {"role": "system", "content": TAG_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=300,
            stream=False,
        ),
        timeout=60,
    )
    return parse_tag_array(resp.choices[0].message.content or "")


@router.get("/{note_id}/tag-suggestions", response_model=NoteTagSuggestionsOut)
async def tag_suggestions(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    ai: bool = False,
    x_note_token: str | None = Header(default=None, alias="X-Note-Token"),
    session: AsyncSession = Depends(get_session),
):
    """返回推荐标签；``ai=1`` 时额外请求大模型给出新标签。

    大模型未配置或调用失败不会影响本地匹配结果，错误通过 ``ai_error`` 返回。
    """
    note = await _get_note(session, kb_id, note_id)
    if note.is_locked and not token_is_valid(note, x_note_token):
        raise HTTPException(403, "笔记已上锁，请先输入密码解锁后再获取建议")
    body = note_body(note, x_note_token)
    tags = await _local_tag_suggestions(session, kb_id, note, body)
    ai_error: str | None = None
    if ai:
        known = {item.name.lower() for item in tags} | {
            tag.name.lower() for tag in note.tags
        }
        try:
            for name in await _ai_tag_suggestions(session, kb_id, note, body):
                key = name.lower()
                if key in known:
                    continue
                known.add(key)
                tags.append(
                    NoteTagSuggestion(name=name, source="ai", evidence="大模型推荐")
                )
        except HTTPException as exc:
            ai_error = str(exc.detail)
        except asyncio.TimeoutError:
            ai_error = "AI 推荐超时，请稍后重试"
        except Exception as exc:  # noqa: BLE001 - 第三方模型异常统一转为提示
            ai_error = f"AI 推荐失败：{exc}"
    return NoteTagSuggestionsOut(tags=tags[:MAX_TAG_SUGGESTIONS], ai_error=ai_error)
