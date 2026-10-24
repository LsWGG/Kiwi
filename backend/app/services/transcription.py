"""本地语音转写：faster-whisper 模型加载、转写结果整理与会议笔记生成。

模型在首次转写时下载并常驻进程；转写本身是 CPU 密集的同步调用，统一放进
线程池，避免阻塞事件循环。未配置大模型时仍会生成带时间戳的转写全文。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KnowledgeBase, LLMConfig, Note
from app.db.session import async_session_factory
from app.services.llm_factory import LLMCrypto, LLMFactory

logger = logging.getLogger("kiwi.transcribe")

SUMMARY_MAX_CHARS = 30_000
SUMMARY_TIMEOUT_SECONDS = 180.0

LANGUAGE_LABELS = {
    "zh": "中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "de": "德语",
    "fr": "法语",
    "es": "西班牙语",
    "ru": "俄语",
}

SUMMARY_PROMPT = """你是严谨的会议记录助手。请根据下面的语音转写整理会议纪要，使用 Markdown 输出：
1. 先用 3-5 句话概括会议主题与结论；
2. 列出关键讨论点；
3. 用 `- [ ]` 列出明确的待办事项（负责人 / 时间未知时不要编造）；
4. 单列「待确认问题」。
只依据转写内容，不要补充不存在的信息；若转写过于零碎，则如实标注。"""

_model = None
_model_lock = threading.Lock()


class TranscriptionError(RuntimeError):
    """转写不可用或音频无法解析。"""


def model_status() -> dict:
    return {
        "enabled": settings.whisper_enabled,
        "model": settings.whisper_model,
        "device": settings.whisper_device,
        "compute_type": settings.whisper_compute_type,
        "model_dir": str(settings.whisper_model_dir),
        "loaded": _model is not None,
    }


def _get_model():
    """懒加载并缓存 WhisperModel（首次会下载模型）。"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                settings.whisper_model_dir.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "加载 faster-whisper 模型 %s（%s / %s）",
                    settings.whisper_model,
                    settings.whisper_device,
                    settings.whisper_compute_type,
                )
                _model = WhisperModel(
                    settings.whisper_model,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute_type,
                    download_root=str(settings.whisper_model_dir),
                )
    return _model


def _run_transcription(path: Path, language: str | None, *, fast: bool = False) -> dict:
    model = _get_model()
    segments, info = model.transcribe(
        str(path),
        language=language,
        # 实时预览用小 beam 换取更低延迟；最终转写仍用 beam=5。
        beam_size=1 if fast else 5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    # segments 是惰性生成器，必须在同一线程内消费完。
    items = [
        {
            "start": round(float(segment.start), 2),
            "end": round(float(segment.end), 2),
            "text": (segment.text or "").strip(),
        }
        for segment in segments
        if (segment.text or "").strip()
    ]
    text = "\n".join(item["text"] for item in items).strip()
    return {
        "text": text,
        "segments": items,
        "language": getattr(info, "language", None) or language or "",
        "language_probability": round(float(getattr(info, "language_probability", 0) or 0), 3),
        "duration": round(float(getattr(info, "duration", 0) or 0), 2),
    }


async def resolve_provider(preference: str | None = None) -> tuple[str, object]:
    """解析转写通道：auto 时「飞书已配置就用飞书，否则本地」。"""
    from app.services import feishu_minutes

    config = await feishu_minutes.load_config()
    choice = (preference or config.provider or "auto").strip().lower()
    if choice not in {"auto", "local", "feishu"}:
        choice = "auto"
    if choice == "local":
        return "local", config
    if choice == "feishu":
        if not config.can_use:
            raise TranscriptionError(
                "已选择飞书妙记，但尚未配置用户访问令牌或刷新令牌"
            )
        return "feishu", config
    return ("feishu", config) if config.can_use else ("local", config)


async def _local_transcribe(path: Path, language: str, *, fast: bool = False) -> dict:
    lang = None if not language or language == "auto" else language
    if not path.exists():
        raise TranscriptionError("音频文件不存在或已被清理")
    try:
        result = await asyncio.to_thread(_run_transcription, path, lang, fast=fast)
    except TranscriptionError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("音频转写失败：%s", path)
        raise TranscriptionError(f"音频转写失败：{e}") from e
    result["provider"] = "local"
    return result


async def transcribe_file(
    path: Path,
    *,
    language: str = "auto",
    provider: str | None = None,
    original_name: str = "",
) -> dict:
    """按系统配置选择飞书妙记或本地 faster-whisper。

    ``auto`` 模式下飞书调用失败会回退本地，保证录音仍能落成笔记；
    显式选择 ``feishu`` 时则把错误直接抛给任务面板。
    """
    from app.services import feishu_minutes

    choice, config = await resolve_provider(provider)
    if choice == "feishu":
        try:
            return await feishu_minutes.transcribe_audio(
                path, original_name=original_name or path.name, config=config
            )
        except feishu_minutes.FeishuNotConfigured as exc:
            if (provider or config.provider) == "feishu":
                raise TranscriptionError(str(exc)) from exc
            logger.warning("飞书妙记未配置，回退本地转写：%s", exc)
        except feishu_minutes.FeishuError as exc:
            if (provider or config.provider) == "feishu" or not settings.whisper_enabled:
                raise TranscriptionError(str(exc)) from exc
            logger.warning("飞书妙记转写失败，回退本地转写：%s", exc)
            result = await _local_transcribe(path, language)
            result["fallback_reason"] = str(exc)
            return result
    if not settings.whisper_enabled:
        raise TranscriptionError("语音转写已关闭，请设置 KIWI_WHISPER_ENABLED=true")
    return await _local_transcribe(path, language)


async def transcribe_preview(path: Path, *, language: str = "auto") -> dict:
    """录音过程中的本地实时预览；失败不影响最终转写。"""
    if not settings.whisper_enabled:
        raise TranscriptionError("本地实时预览已关闭")
    return await _local_transcribe(path, language, fast=True)


async def build_status() -> dict:
    """转写通道与本地模型状态，供设置页与录音弹窗展示。"""
    from app.services import feishu_minutes

    try:
        config = await feishu_minutes.load_config()
        feishu_configured = config.can_use
        requested = config.provider or "auto"
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取飞书妙记配置失败：%s", exc)
        feishu_configured = False
        requested = "auto"
    active = "feishu" if requested == "feishu" or (requested == "auto" and feishu_configured) else "local"
    return {
        "enabled": bool(settings.whisper_enabled or feishu_configured),
        "provider": active,
        "provider_setting": requested,
        "provider_ready": feishu_configured if active == "feishu" else bool(settings.whisper_enabled),
        "feishu_configured": feishu_configured,
        "preview_enabled": bool(settings.whisper_enabled),
        "local": model_status(),
    }


async def _resolve_llm(
    session: AsyncSession, kb_id: uuid.UUID
) -> tuple[LLMConfig, str] | None:
    kb = await session.get(KnowledgeBase, kb_id)
    cfg: LLMConfig | None = None
    if kb is not None and kb.llm_config_id:
        cfg = await session.get(LLMConfig, kb.llm_config_id)
    if cfg is None:
        cfg = (
            await session.execute(
                select(LLMConfig).where(LLMConfig.is_default.is_(True))
            )
        ).scalars().first()
    if cfg is None:
        return None
    api_key = (
        LLMCrypto.decrypt(cfg.encrypted_api_key)
        if cfg.encrypted_api_key
        else "ollama"
    )
    return cfg, api_key


async def summarize_transcript(text: str, kb_id: uuid.UUID) -> str:
    """可选的会议纪要生成；未配置大模型或调用失败时返回空串。"""
    if not text.strip():
        return ""
    try:
        async with async_session_factory() as session:
            resolved = await _resolve_llm(session, kb_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("解析大模型配置失败，跳过会议摘要：%s", e)
        return ""
    if resolved is None:
        return ""
    cfg, api_key = resolved
    client = LLMFactory().get_client(cfg.base_url, api_key or None, cfg.model_name)
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=cfg.model_name,
                messages=[
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {
                        "role": "user",
                        "content": f"语音转写内容：\n{text[:SUMMARY_MAX_CHARS]}",
                    },
                ],
                temperature=0.2,
                max_tokens=1800,
            ),
            timeout=SUMMARY_TIMEOUT_SECONDS,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("会议摘要生成失败，仅保留转写全文：%s", e)
        return ""
    content = response.choices[0].message.content if response.choices else ""
    return (content or "").strip()


def _stamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _duration(seconds: float) -> str:
    return _stamp(seconds)


def language_label(code: str) -> str:
    if not code:
        return "自动识别"
    return LANGUAGE_LABELS.get(code, code)


def render_markdown(
    result: dict,
    *,
    original_name: str,
    summary: str = "",
) -> str:
    provider = (result.get("provider") or "local").lower()
    engine = "飞书妙记" if provider == "feishu" else f"本地 {settings.whisper_model}"
    meta = (
        f"> 来源音频：{original_name or '未命名音频'} · 时长 "
        f"{_duration(result.get('duration', 0))} · 语言 "
        f"{language_label(result.get('language', ''))} · 转写引擎 {engine}"
    )
    lines = [meta]
    minute_url = str(result.get("minute_url") or "")
    if minute_url:
        lines.append(f"> 妙记链接：{minute_url}")
    if result.get("fallback_reason"):
        lines.append(
            f"> 提示：飞书妙记调用失败，已回退本地转写（{result['fallback_reason']}）"
        )
    lines.append("")
    if summary:
        lines.extend(["## 会议摘要", "", summary, ""])
    lines.extend(["## 转写全文", ""])
    segments = result.get("segments") or []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- **{_stamp(segment.get('start', 0))}** {text}")
    if not segments:
        lines.append(result.get("text") or "（未识别到语音内容）")
    return "\n".join(lines).strip() + "\n"


async def create_note_from_transcript(
    session: AsyncSession,
    *,
    kb_id: uuid.UUID,
    title: str,
    original_name: str,
    result: dict,
    summary: str = "",
) -> Note:
    final_title = (title or "").strip() or Path(original_name).stem or "语音转写"
    note = Note(
        kb_id=kb_id,
        title=final_title[:300],
        kind="doc",
        status="active",
        body_md=render_markdown(
            result, original_name=original_name, summary=summary
        ),
        props_json={
            "source": "transcription",
            "audio": {
                "filename": original_name,
                "duration": result.get("duration", 0),
                "language": result.get("language", ""),
                "provider": result.get("provider", "local"),
                "model": (
                    "feishu-minutes"
                    if result.get("provider") == "feishu"
                    else settings.whisper_model
                ),
                "minute_url": result.get("minute_url", ""),
            },
        },
    )
    session.add(note)
    await session.commit()
    return note


def default_title(filename: str) -> str:
    stem = Path(filename or "").stem.strip()
    if stem:
        return stem[:300]
    return f"语音转写 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
