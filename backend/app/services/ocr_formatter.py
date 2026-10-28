"""OCR 结果二次处理：基础清洗后交给大模型整理为规范 Markdown。

线上 OCR 模型只负责「把图片变成文字」，其输出可能带有 grounding 标记、
JSON 外壳、花括号噪声或断行。这里在入库 / 生成笔记前再做一次排版整理，
并严格保留原文语言，不翻译、不扩写。
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from sqlalchemy import select

from app.config import settings
from app.db.models import KnowledgeBase, LLMConfig
from app.db.session import async_session_factory
from app.services.llm_factory import LLMCrypto, LLMFactory
from app.services.parser import ParsedDocument

logger = logging.getLogger("kiwi.ocr.format")

MAX_CHUNK_CHARS = 6000
MAX_CONCURRENCY = 2
FORMAT_PROMPT = (
    "你是文档排版助手。把用户提供的 OCR 原始文本整理为结构清晰、可直接编辑的 Markdown。\n"
    "规则：\n"
    "1. 严格保留原文语言，不得翻译；\n"
    "2. 只做排版整理与明显的 OCR 错误修复，不得增加原文没有的事实、标题或结论；\n"
    "3. 合理使用标题、段落、列表、引用、表格和公式；没有把握时不要编造表格；\n"
    "4. 删除 JSON 花括号、控制标记、重复乱码等噪声；\n"
    "5. 删除页眉、页脚、页码、水印等与正文无关的内容，不要把它们当作正文保留；\n"
    "6. 如果原文包含 Markdown 图片链接（形如 ![说明](/media/...)），必须原样保留"
    "每个链接及其相对顺序，不得删除、改写、合并或用文字替代；\n"
    "7. 不要输出任何解释、前言或结语，也不要用代码围栏包裹整篇文档。"
)
_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n?(.*?)\n?```$", re.S | re.I)
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)\s]+(?:\s+[\"'][^\"']*[\"'])?\)")
_IMAGE_URL_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")


def is_ocr_engine(engine: str) -> bool:
    """判断解析引擎是否为 OCR（线上视觉模型或本地 tesseract）。"""
    return engine == "tesseract-ocr" or engine.startswith("online-ocr:")


async def _resolve_llm_config(kb_id: uuid.UUID) -> tuple[LLMConfig | None, str]:
    """按知识库默认 > 系统默认解析大模型配置。"""
    async with async_session_factory() as db:
        kb = await db.get(KnowledgeBase, kb_id)
        cfg: LLMConfig | None = None
        if kb is not None and kb.llm_config_id:
            cfg = await db.get(LLMConfig, kb.llm_config_id)
        if cfg is None:
            cfg = (
                (await db.execute(select(LLMConfig).where(LLMConfig.is_default.is_(True))))
                .scalars()
                .first()
            )
        if cfg is None:
            return None, ""
        api_key = LLMCrypto.decrypt(cfg.encrypted_api_key) if cfg.encrypted_api_key else ""
        return cfg, api_key


def _split_chunks(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """按段落切块，尽量不切断段落；超长段落再按行切分。"""
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= limit:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current.strip():
            chunks.append(current.strip())
        current = ""
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = limit
            piece = para[:cut].strip()
            if piece:
                chunks.append(piece)
            para = para[cut:].lstrip("\n")
        current = para
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk.strip()]


def _clean_model_output(raw: str) -> str:
    value = (raw or "").strip()
    match = _FENCE_RE.match(value)
    if match:
        value = match.group(1).strip()
    return value


async def format_ocr_document(parsed: ParsedDocument, kb_id: uuid.UUID) -> ParsedDocument:
    """把 OCR 解析结果整理为 Markdown；任何失败都保留清洗后的原文。"""
    if not is_ocr_engine(parsed.parse_engine) or not (parsed.text or "").strip():
        return parsed

    try:
        cfg, api_key = await _resolve_llm_config(kb_id)
    except Exception as exc:  # noqa: BLE001 —— 配置解析失败不应阻断导入
        logger.warning("读取 OCR 排版大模型配置失败：%s", exc)
        cfg, api_key = None, ""

    if cfg is None:
        parsed.warnings.append("未配置大模型，OCR 结果已做基础清洗但未进行结构化排版")
        parsed.quality_report = {
            **(parsed.quality_report or {}),
            "llm_format": {"enabled": False, "reason": "no_llm_config"},
        }
        return parsed

    source_images = _IMAGE_MD_RE.findall(parsed.text)
    chunks = _split_chunks(parsed.text)
    if not chunks:
        return parsed

    client = LLMFactory().get_client(cfg.base_url, api_key or None, cfg.model_name)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    failures = 0
    timeout = max(60.0, float(settings.llm_timeout or 0))

    async def format_chunk(chunk: str) -> str:
        nonlocal failures
        try:
            async with semaphore:
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=cfg.model_name,
                        messages=[
                            {"role": "system", "content": FORMAT_PROMPT},
                            {"role": "user", "content": chunk},
                        ],
                        temperature=0.1,
                    ),
                    timeout=timeout,
                )
            choice = response.choices[0]
            if getattr(choice, "finish_reason", None) == "length":
                raise ValueError("大模型输出被截断")
            output = _clean_model_output(choice.message.content or "")
            return output or chunk
        except Exception as exc:  # noqa: BLE001 —— 单段失败保留原文
            failures += 1
            logger.warning("OCR 大模型排版失败，保留该段原文：%s", exc)
            return chunk

    formatted = await asyncio.gather(*(format_chunk(chunk) for chunk in chunks))
    text = "\n\n".join(part.strip() for part in formatted if part.strip()).strip()
    if source_images:
        # 排版模型有时会「顺手」删掉图片链接；按 URL 检查后把遗漏的补回，
        # 宁可位置不完美，也不能让裁剪出来的图凭空消失。
        present = set(_IMAGE_URL_RE.findall(text))
        missing: list[str] = []
        for image in source_images:
            match = _IMAGE_URL_RE.search(image)
            url = match.group(1) if match else image
            if url not in present:
                missing.append(image)
        if missing:
            text = "\n\n".join([text, *missing]).strip()
            parsed.warnings.append(
                f"已补回 {len(missing)} 个被排版模型遗漏的图片链接"
            )
    parsed.text = text or parsed.text
    parsed.quality_report = {
        **(parsed.quality_report or {}),
        "llm_format": {
            "enabled": True,
            "model": cfg.model_name,
            "chunks": len(chunks),
            "failed_chunks": failures,
        },
    }
    if failures:
        parsed.warnings.append(f"OCR 排版整理有 {failures} 段失败，已保留对应原文")
    else:
        parsed.warnings.append(f"已使用大模型 {cfg.model_name} 将 OCR 结果整理为 Markdown")
    return parsed
