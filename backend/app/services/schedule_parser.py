"""把自然语言计划解析为 cron：优先使用已配置的大模型，失败时回退规则解析。"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from sqlalchemy import select

from app.config import settings
from app.db.models import LLMConfig
from app.db.session import async_session_factory
from app.services import cron_schedule
from app.services.llm_factory import LLMCrypto, llm_factory

logger = logging.getLogger("kiwi.schedule")


class ScheduleParseError(ValueError):
    pass


_SYSTEM = """你是 Kiwi 定时任务解析器。把用户的计划转成标准 5 段 cron（分 时 日 月 周，
周日=0；不要秒、年份或 6 段），只输出 JSON，不要解释：
{"cron":"0 9 * * *","description":"每天 09:00"}

规则：
- 每天/每日：日=*，周=*；工作日：周=1-5；每周X：周为 0-6；每月 N 号：日=N，周=*。
- 每 N 分钟：*/N * * * *；每 N 小时：0 */N * * *；每小时：0 * * * *。
- 时间一律 24 小时制；「下午 / 晚上」要加 12 小时。
- 用户没有明确时间或频率时，cron 返回空字符串，不要猜测。
- description 用简短中文描述，例如「每工作日 08:30」。"""


def _extract_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def _llm_parse(text: str, session=None) -> tuple[str, str] | None:
    async def run(db) -> tuple[str, str] | None:
        cfg = (
            (
                await db.execute(
                    select(LLMConfig).where(LLMConfig.is_default.is_(True))
                )
            )
            .scalars()
            .first()
        )
        if cfg is None:
            return None
        try:
            api_key = (
                LLMCrypto.decrypt(cfg.encrypted_api_key)
                if cfg.encrypted_api_key
                else "ollama"
            )
        except Exception:  # noqa: BLE001
            return None
        model = (settings.agent_planner_model or cfg.model_name or "").strip()
        if not model or not cfg.base_url:
            return None
        client = llm_factory.get_client(cfg.base_url, api_key or None, model)
        from datetime import datetime

        from app.services.agent_planner import app_timezone

        current = datetime.now(app_timezone())
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"当前时间：{current.strftime('%Y-%m-%d %H:%M')}\n"
                            f"用户计划：{text}"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=300,
            ),
            timeout=max(5.0, settings.agent_planner_timeout),
        )
        content = ""
        if response.choices:
            content = response.choices[0].message.content or ""
        data = _extract_json(content)
        if not data:
            return None
        cron = str(data.get("cron") or "").strip()
        if not cron:
            return None
        try:
            cron = cron_schedule.validate_cron(cron)
        except cron_schedule.CronError:
            return None
        description = str(data.get("description") or "").strip()[:120]
        return cron, description or cron_schedule.describe(cron)

    if session is not None:
        return await run(session)
    async with async_session_factory() as db:
        return await run(db)


async def parse_schedule(text: str, *, session=None) -> tuple[str, str]:
    """返回 (cron, 中文描述)；优先大模型，失败回退确定性规则。"""
    raw = (text or "").strip()
    if not raw:
        raise ScheduleParseError("请填写计划，例如「每天早上九点」")
    if len(raw.split()) == 5:
        try:
            cron = cron_schedule.validate_cron(raw)
        except cron_schedule.CronError as exc:
            raise ScheduleParseError(str(exc)) from exc
        return cron, cron_schedule.describe(cron)

    try:
        llm = await _llm_parse(raw, session)
    except Exception:  # noqa: BLE001 —— 模型失败不能阻断规则解析
        logger.warning("大模型解析计划失败，回退规则解析", exc_info=True)
        llm = None
    if llm is not None:
        return llm
    try:
        return cron_schedule.natural_to_cron(raw)
    except cron_schedule.CronError as exc:
        raise ScheduleParseError(str(exc)) from exc


__all__ = ["ScheduleParseError", "parse_schedule"]
