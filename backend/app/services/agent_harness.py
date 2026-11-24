"""问答 Agent Harness：计划 → 工具 → 观察 → 最终回答。

协议（JSON，不使用各家不一致的原生 tool calling）::

    {"thought": "...", "plan": ["..."],
     "action": {"tool": "search_notes", "args": {...}, "summary": "..."} | null,
     "answer": "action 为 null 时的最终回答"}

读工具自动执行；写工具先登记到 ``agent_actions`` 并结束本轮 SSE，等用户
确认后由前端携带 ``resume_action_id`` 继续同一个 Agent 循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from string import Template
from typing import Any, AsyncIterator

from openai import APIConnectionError, APIStatusError, APITimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.mcp import Toolbox
from app.schemas.chat import Citation
from app.services import (
    agent_actions,
    agent_fast_path,
    agent_tools,
    agent_trace,
    agent_undo,
)
from app.services.agent_planner import app_timezone
from app.services.metrics import metrics

logger = logging.getLogger("kiwi.agent")

MAX_TOOL_RESULT = 64_000
MAX_UI_RESULT = 6_000
_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "agent_system.md"

Event = tuple[str, dict[str, Any]]


@dataclass
class AgentContext:
    messages: list[dict]
    citations: list[Citation]
    intent: str
    client: Any
    model_name: str
    temperature: float
    kb_id: uuid.UUID | None
    kb_ids: list[uuid.UUID]
    llm_config_id: uuid.UUID | None
    model_override: str | None
    scope_mode: str
    plan: list[dict] = field(default_factory=list)
    # 本轮可见的工具集（内置 + 外部 MCP）；为空时由 run_agent 延迟加载。
    toolbox: Toolbox | None = None
    # 用户这一轮的原话，用于快路径资格判断；为空表示不做快路径。
    user_query: str = ""
    # 单次模型调用超时（秒）；0 表示使用客户端默认值。
    completion_timeout: float = 0.0
    # 检索规划阶段的来源与耗时，随本轮 trace 一起展示。
    planner_source: str = ""
    planner_ms: float = 0.0
    planner_queries: int = 0
    planner_input: dict[str, Any] = field(default_factory=dict)
    planner_output: dict[str, Any] = field(default_factory=dict)
    # 最近一次模型调用的 usage / finish_reason / 尝试次数，供 trace 记录。
    last_usage: dict[str, int] = field(default_factory=dict)
    last_finish_reason: str = ""
    last_attempts: int = 0
    # 由检索准备阶段提前创建的 trace；为空时 run_agent 自己创建。
    trace: agent_trace.AgentTrace | None = None


class AgentFormatError(Exception):
    pass


@dataclass
class AgentReply:
    thought: str = ""
    plan: list[str] = field(default_factory=list)
    action: dict[str, Any] | None = None
    answer: str = ""
    raw: str = ""


def _prompt_template() -> str:
    """读取系统提示模板；自定义文件优先，缺省回落到内置模板。"""
    candidates: list[Path] = []
    if settings.agent_prompt_file:
        candidates.append(Path(settings.agent_prompt_file))
    candidates.append(_PROMPT_FILE)
    for path in candidates:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Agent 提示模板不可读：%s", path)
    return (
        "## Agent 工具与行动协议\n$tool_prompt\n权限：$permission\n"
        "当前日期：$current_date（星期$weekday，$timezone）\n"
        "最多 $max_steps 次工具调用。"
    )


def agent_system_prompt(
    *,
    can_write: bool,
    toolbox: Toolbox,
    max_steps: int,
) -> str:
    permission = (
        "当前问题限定在单个知识库内，写工具可用，但必须先请求用户确认。"
        if can_write
        else "当前为多库 / 全局范围：读工具可用，写工具不可用；若用户要求编辑，请提示其切换到单个知识库。"
    )
    now = datetime.now(app_timezone())
    weekday = "一二三四五六日"[now.weekday()]
    monday = now - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    return Template(_prompt_template()).safe_substitute(
        tool_prompt=toolbox.prompt(),
        permission=permission,
        current_date=now.strftime("%Y-%m-%d"),
        weekday=weekday,
        week_start=monday.strftime("%Y-%m-%d"),
        week_end=sunday.strftime("%Y-%m-%d"),
        timezone=settings.timezone or "本地时区",
        max_steps=str(max_steps),
    )


def build_messages(
    openai_msgs: list[dict],
    *,
    kb_id: uuid.UUID | None,
    can_write: bool,
    toolbox: Toolbox | None = None,
    max_steps: int | None = None,
) -> list[dict]:
    """在原有 RAG 系统提示后追加工具协议与权限说明。"""
    messages = [dict(item) for item in openai_msgs]
    box = toolbox or Toolbox(agent_tools.builtin_tools())
    limit = max(1, max_steps or settings.agent_max_steps)
    extra = "\n\n" + agent_system_prompt(
        can_write=can_write, toolbox=box, max_steps=limit
    ).strip() + "\n"
    if messages and messages[0].get("role") == "system":
        messages[0] = {
            **messages[0],
            "content": str(messages[0].get("content") or "") + extra,
        }
    else:
        messages.insert(0, {"role": "system", "content": extra.strip()})
    return messages


def _extract_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                value, _end = decoder.raw_decode(candidate[index:])
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _normalize_plan(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    steps: list[dict] = []
    for index, item in enumerate(raw[:12], start=1):
        if isinstance(item, str):
            title = item.strip()
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("step") or "").strip()
        else:
            title = str(item).strip()
        if title:
            steps.append({"id": f"plan-{index}", "title": title[:200], "status": "pending"})
    return steps


def parse_reply(text: str) -> AgentReply:
    data = _extract_json(text)
    if data is None:
        # 模型没有按协议输出时，把全文当作最终回答，避免整轮失败。
        return AgentReply(answer=(text or "").strip(), raw=text or "")
    if not data.keys() & {"thought", "plan", "action", "answer"}:
        # 用户让模型直接输出一段 JSON（如配置示例）时，不要把业务 JSON
        # 误判成 Agent 协议；整段文本就是最终回答。
        return AgentReply(answer=(text or "").strip(), raw=text or "")
    reply = AgentReply(raw=text or "")
    reply.thought = str(data.get("thought") or "").strip()[:1000]
    reply.plan = [step["title"] for step in _normalize_plan(data.get("plan"))]
    answer = data.get("answer")
    if isinstance(answer, str):
        reply.answer = answer.strip()
    action = data.get("action")
    if isinstance(action, dict) and action.get("tool"):
        args = action.get("args")
        reply.action = {
            "tool": str(action.get("tool") or "").strip(),
            "args": args if isinstance(args, dict) else {},
            "summary": str(action.get("summary") or "").strip(),
            "step": action.get("step"),
        }
    return reply


# 部分模型（如 DeepSeek 系列）会无视「只返回 JSON」的约定，直接输出原生工具
# 调用标记。这些标记不能当回答展示，也不该让用户自己重问；先尝试转成协议动作，
# 转不了再要求模型按 JSON 重试。
_DSML_MARKER_RE = re.compile(r"｜｜DSML｜｜|<\|DSML\|")
_DSML_INVOKE_RE = re.compile(
    r"<[｜|]{2}\s*DSML\s*[｜|]{2}\s*invoke\b([^>]*)>(.*?)</[｜|]{2}\s*DSML\s*[｜|]{2}\s*invoke>",
    re.S,
)
_DSML_PARAM_RE = re.compile(
    r"<[｜|]{2}\s*DSML\s*[｜|]{2}\s*parameter\b([^>]*)>(.*?)</[｜|]{2}\s*DSML\s*[｜|]{2}\s*parameter>",
    re.S,
)
_DSML_ATTR_RE = re.compile(r'([A-Za-z_][\w-]*)\s*=\s*"([^"]*)"')


def _dsml_attrs(raw: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in _DSML_ATTR_RE.finditer(raw)}


def _dsml_value(raw: str, string_flag: str | None) -> Any:
    if string_flag == "true":
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _parse_dsml_reply(text: str) -> AgentReply | None:
    """把原生工具调用标记转换为 Agent 协议动作；无法解析时返回 None。"""
    if not text or not _DSML_MARKER_RE.search(text):
        return None
    for invoke in _DSML_INVOKE_RE.finditer(text):
        tool = (_dsml_attrs(invoke.group(1)).get("name") or "").strip()
        if not tool:
            continue
        args: dict[str, Any] = {}
        for param in _DSML_PARAM_RE.finditer(invoke.group(2)):
            attrs = _dsml_attrs(param.group(1))
            name = (attrs.get("name") or "").strip()
            if name:
                args[name] = _dsml_value(param.group(2), attrs.get("string"))
        action = {"tool": tool, "args": args, "summary": "", "step": None}
        # 写回历史的 raw 使用协议 JSON，避免模型在下一轮继续模仿原生标记。
        normalized = json.dumps(
            {"thought": "", "plan": [], "action": action}, ensure_ascii=False
        )
        logger.info("已把模型的原生工具调用转换为协议动作：%s", tool)
        return AgentReply(action=action, raw=normalized)
    return None


def _parse_reply_with_dsml(text: str) -> AgentReply:
    reply = _parse_dsml_reply(text)
    return reply if reply is not None else parse_reply(text)


def answer_echoes_prompt(answer: str, prompt: str) -> bool:
    """回答是否在复述 Agent 系统提示。

    模型偶尔会把自己的工具清单、权限或日期说明当成资料抄进回答，用户完全
    看不懂。这里按「成句复述」判断：回答里有两行以上较长的原文出现在提示中，
    才认定跑偏；只提到一两个工具名不会误判。
    """
    if not answer or not prompt:
        return False
    hits = 0
    for line in answer.splitlines():
        text = line.strip().lstrip("-*#> ").strip()
        if len(text) < 12:
            continue
        if text in prompt:
            hits += 1
            if hits >= 2:
                return True
    return False


def _tool_result_text(result: dict) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_RESULT:
        text = text[:MAX_TOOL_RESULT] + "…（结果过长已截断）"
    return text


def _tool_result_ui(result: dict) -> dict:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > MAX_UI_RESULT:
        return {"truncated": True, "preview": text[:MAX_UI_RESULT] + "…"}
    return result


# 回答里的站内链接：[标题](kiwi://note/<id>) / [@标题](kiwi://wiki/<id>?x=y)。
_LINK_TARGET_RE = re.compile(r"\[([^\]]*)\]\(kiwi://(note|wiki)/([^)\s]+)\)")


def _canonical_uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def _title_key(title: str) -> str:
    return " ".join(title.lstrip("@").split()).strip().lower()


def _collect_link_targets(result: Any, out: dict[str, str]) -> None:
    """收集工具结果里可引用的笔记 / Wiki（id + 标题）。

    模型在最终回答里要把受影响的笔记写成站内链接，但偶发会把 UUID 抄错一两个
    字符；把本轮真实出现的 id 与标题记下来，才能在输出前修正链接。
    """
    if isinstance(result, dict):
        title = result.get("title")
        if isinstance(title, str) and title.strip():
            for key in ("id", "note_id", "wiki_id"):
                raw = result.get(key)
                if isinstance(raw, str):
                    canonical = _canonical_uuid(raw)
                    if canonical:
                        out.setdefault(canonical, title.strip())
        for value in result.values():
            _collect_link_targets(value, out)
    elif isinstance(result, list):
        for item in result:
            _collect_link_targets(item, out)


def _repair_note_links(answer: str, known: dict[str, str]) -> str:
    """修正模型回答里指向本轮笔记的站内链接。

    UUID 抄错后点击会请求一个非法 id，笔记面板直接报 422。这里先按链接文字
    匹配标题，再按 id 相似度匹配；对不上的降级为纯文本，避免死链。
    """
    if not answer or "kiwi://" not in answer:
        return answer

    by_title: dict[str, list[str]] = {}
    for known_id, title in known.items():
        by_title.setdefault(_title_key(title), []).append(known_id)

    def replace(match: re.Match[str]) -> str:
        label, kind, raw = match.group(1), match.group(2), match.group(3)
        target = raw.split("?", 1)[0]
        rest = raw[len(target) :]
        if _canonical_uuid(target) is not None:
            # 合法 UUID：可能是本轮结果，也可能来自更早的上下文，保持原样。
            return match.group(0)

        # 1) 链接文字通常就是笔记标题，最可靠。
        candidates = by_title.get(_title_key(label), [])
        if len(candidates) == 1:
            logger.info("修正回答中的笔记链接：%s -> %s", target, candidates[0])
            return f"[{label}](kiwi://{kind}/{candidates[0]}{rest})"

        # 2) 标题对不上时按 id 相似度兜底（少抄 / 多抄一两个字符）。
        target_hex = target.replace("-", "").lower()
        scored: list[tuple[float, str]] = []
        for known_id in known:
            known_hex = known_id.replace("-", "")
            if abs(len(target_hex) - len(known_hex)) > 4:
                continue
            scored.append(
                (SequenceMatcher(None, target_hex, known_hex).ratio(), known_id)
            )
        scored.sort(reverse=True)
        if scored and scored[0][0] >= 0.9 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.04
        ):
            logger.info("修正回答中的笔记链接：%s -> %s", target, scored[0][1])
            return f"[{label}](kiwi://{kind}/{scored[0][1]}{rest})"

        # 3) 对不上：宁可少一个可点链接，也不要让用户点进 422。
        logger.warning("回答中的笔记链接无法修正，已降级为纯文本：%s", target)
        return label

    return _LINK_TARGET_RE.sub(replace, answer)


def _mark_plan(plan: list[dict], index: Any, status: str) -> None:
    try:
        position = int(index) - 1
    except (TypeError, ValueError):
        return
    if 0 <= position < len(plan):
        plan[position]["status"] = status


def _undo_fields(record: agent_undo.UndoRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    return {"undo_id": record.id, "undo_label": record.label}


def _finalize_plan(plan: list[dict]) -> None:
    for step in plan:
        if step.get("status") in ("pending", "active"):
            step["status"] = "done"


def _history(messages: list[dict]) -> list[dict]:
    """只保留 system / user / assistant 文本，避免把内部字段带给上游。"""
    result: list[dict] = []
    for item in messages:
        role = item.get("role")
        content = item.get("content")
        if role in ("system", "user", "assistant") and isinstance(content, str):
            result.append({"role": role, "content": content})
    return result


MAX_LLM_RETRIES = 2
LLM_RETRY_DELAY = 1.2


async def _complete(ctx: AgentContext) -> str:
    attempts = 0
    ctx.last_usage = {}
    ctx.last_finish_reason = ""
    ctx.last_attempts = 0
    while True:
        try:
            call = ctx.client.chat.completions.create(
                model=ctx.model_name,
                messages=_history(ctx.messages),
                stream=False,
                temperature=ctx.temperature,
            )
            if ctx.completion_timeout and ctx.completion_timeout > 0:
                response = await asyncio.wait_for(
                    call, timeout=ctx.completion_timeout
                )
            else:
                response = await call
            break
        except asyncio.TimeoutError:
            if attempts >= MAX_LLM_RETRIES:
                raise
            attempts += 1
            logger.warning(
                "模型调用超时，第 %s/%s 次重试", attempts, MAX_LLM_RETRIES
            )
            await asyncio.sleep(LLM_RETRY_DELAY * attempts)
        except (APIConnectionError, APITimeoutError) as e:
            # 代理或网络偶发断连：已确认的写操作之后继续生成总结时也会遇到，
            # 直接失败会让用户以为操作没成功。短暂退避后重试。
            if attempts >= MAX_LLM_RETRIES:
                raise
            attempts += 1
            logger.warning(
                "模型连接失败（%s），第 %s/%s 次重试",
                type(e).__name__,
                attempts,
                MAX_LLM_RETRIES,
            )
            await asyncio.sleep(LLM_RETRY_DELAY * attempts)
        except APIStatusError as e:
            if e.status_code not in (429, 500, 502, 503, 504) or attempts >= MAX_LLM_RETRIES:
                raise
            attempts += 1
            logger.warning(
                "模型服务返回 %s，第 %s/%s 次重试",
                e.status_code,
                attempts,
                MAX_LLM_RETRIES,
            )
            await asyncio.sleep(LLM_RETRY_DELAY * attempts)
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise AgentFormatError("模型没有返回内容")
    usage = getattr(response, "usage", None)
    if usage is not None:
        ctx.last_usage = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(
                getattr(usage, "completion_tokens", 0) or 0
            ),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
    ctx.last_finish_reason = str(
        getattr(choices[0], "finish_reason", "") or ""
    )
    ctx.last_attempts = attempts + 1
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    return str(content or "")


def _context_from_pending(
    pending: agent_actions.PendingAction,
    *,
    client: Any,
    model_name: str,
    temperature: float,
    scope_mode: str | None = None,
) -> AgentContext:
    kb_id = uuid.UUID(pending.kb_id) if pending.kb_id else None
    kb_ids = [uuid.UUID(item) for item in pending.kb_ids]
    return AgentContext(
        messages=[dict(item) for item in pending.messages],
        citations=[Citation.model_validate(item) for item in pending.citations],
        intent=pending.intent,
        client=client,
        model_name=model_name,
        temperature=temperature,
        kb_id=kb_id,
        kb_ids=kb_ids,
        llm_config_id=uuid.UUID(pending.llm_config_id) if pending.llm_config_id else None,
        model_override=pending.model_override,
        scope_mode=scope_mode or pending.scope_mode,
        plan=[dict(step) for step in pending.plan],
    )


async def run_agent(
    ctx: AgentContext,
    session: AsyncSession,
    *,
    resume: agent_actions.PendingAction | None = None,
    approved: bool = True,
) -> AsyncIterator[Event]:
    """执行一轮 Agent 循环，按 SSE 事件产出。"""
    can_write = ctx.scope_mode == "kb" and len(ctx.kb_ids) == 1 and ctx.kb_id is not None
    toolbox = ctx.toolbox
    if toolbox is None:
        toolbox = await agent_tools.load_toolbox()
        ctx.toolbox = toolbox
    max_steps = max(1, settings.agent_max_steps)
    # 用于校验回答是否把系统提示当成资料复述；与 build_messages 注入的协议一致。
    protocol_prompt = agent_system_prompt(
        can_write=can_write, toolbox=toolbox, max_steps=max_steps
    )
    trace = ctx.trace or agent_trace.start_trace(
        query=ctx.user_query,
        query_chars=len(ctx.user_query),
        model=ctx.model_name,
        scope=ctx.scope_mode,
        planner_source=ctx.planner_source,
        planner_ms=ctx.planner_ms,
        planner_queries=ctx.planner_queries,
    )
    ctx.trace = trace
    trace.model = ctx.model_name or trace.model
    # 前端用这个 ID 在「设置 → 运维 → Agent 轨迹」里定位本轮流转。
    yield "trace", {"trace_id": trace.id}
    if (
        ctx.planner_input or ctx.planner_output
    ) and not any(event["kind"] == "planner" for event in trace.events):
        trace.event(
            "planner",
            "检索规划",
            ms=ctx.planner_ms,
            input=ctx.planner_input,
            output=ctx.planner_output,
            meta={"source": ctx.planner_source, "queries": ctx.planner_queries},
        )
    plan = [dict(step) for step in ctx.plan]
    # 本轮工具真正返回过的笔记 / Wiki，用于修正模型回答里抄错的链接 id。
    known_links: dict[str, str] = {}
    # 确认执行成功的写操作；后续模型若断连，用它给出确定性的完成回执。
    last_write: tuple[str, dict[str, Any]] | None = None
    undo_record: agent_undo.UndoRecord | None = None
    if resume is not None:
        if not approved:
            trace.finish("cancelled")
            metrics.inc("kiwi_agent_turns_total", {"status": "cancelled"})
            yield "stage", {
                "stage": "approve",
                "status": "done",
                "message": f"已取消：{resume.label}",
            }
            yield "chunk", {"text": f"已取消「{resume.label}」，没有对知识库做任何修改。"}
            yield "done", {"ok": True, "cancelled": True}
            return
        plan = [dict(step) for step in resume.plan]
        yield "stage", {
            "stage": "approve",
            "status": "done",
            "message": f"已确认：{resume.label}",
        }
        yield "stage", {
            "stage": "execute",
            "status": "start",
            "message": f"正在执行：{resume.label}",
        }
        undo_snapshot = await agent_undo.capture_before(
            session, ctx.kb_id, resume.tool, resume.args
        )
        _tool_started = time.perf_counter()
        try:
            result = await toolbox.execute(
                session, ctx.kb_id, resume.tool, resume.args
            )
            ok = True
            summary = resume.summary or "操作已完成"
        except agent_tools.ToolError as e:
            result = {"ok": False, "error": str(e)}
            ok = False
            summary = str(e)
        _tool_elapsed = time.perf_counter() - _tool_started
        trace.event(
            "tool",
            resume.tool,
            ms=_tool_elapsed * 1000,
            ok=ok,
            detail=resume.label,
            input={"tool": resume.tool, "args": resume.args},
            output=result,
            meta={"read_only": False, "label": resume.label},
        )
        metrics.observe(
            "kiwi_agent_tool_seconds",
            _tool_elapsed,
            {"tool": resume.tool, "ok": str(ok).lower()},
        )
        _collect_link_targets(result, known_links)
        if ok:
            last_write = (resume.label, result)
            if ctx.kb_id is not None:
                undo_record = agent_undo.register(
                    tool=resume.tool,
                    kb_id=ctx.kb_id,
                    label=resume.label,
                    snapshot=undo_snapshot,
                    result=result,
                )
        yield "tool_result", {
            "tool": resume.tool,
            "label": resume.label,
            "ok": ok,
            "summary": summary,
            "data": _tool_result_ui(result),
        }
        yield "stage", {
            "stage": "execute",
            "status": "done" if ok else "error",
            "message": f"{resume.label}{'完成' if ok else '失败'}",
            "detail": "" if ok else summary,
        }
        ctx.messages.append({"role": "assistant", "content": resume.assistant_content})
        ctx.messages.append(
            {
                "role": "user",
                "content": (
                    f"用户已批准并执行工具 {resume.tool}。执行结果：\n"
                    f"{_tool_result_text(result)}\n\n"
                    "请根据结果继续。不要重复执行同一操作；若任务已完成，"
                    '返回 {"action": null, "answer": "..."}。'
                ),
            }
        )

    yield "stage", {"stage": "agent", "status": "start", "message": "正在分析并规划操作"}
    tool_steps = 0
    attempts = 0
    leak_retries = 0
    native_retries = 0
    fast_tool: str | None = None
    fast_result: dict[str, Any] | None = None
    try:
        while tool_steps < max_steps and attempts < max_steps * 2:
            attempts += 1
            fast_action = (
                agent_fast_path.build_after_read_tool(
                    ctx.user_query,
                    fast_tool,
                    fast_result or {},
                    can_write=can_write,
                    plan=plan,
                )
                if fast_tool
                else None
            )
            fast_tool = None
            fast_result = None
            if fast_action is not None:
                logger.info(
                    "Agent 快路径：%s → %s", fast_action.get("tool"), fast_action.get("summary")
                )
                trace.event(
                    "fast_path",
                    fast_action["tool"],
                    detail=str(fast_action.get("summary") or ""),
                    input={"query": ctx.user_query},
                    output={
                        "tool": fast_action["tool"],
                        "args": fast_action["args"],
                        "summary": fast_action.get("summary") or "",
                    },
                    meta={"reason": "确定性任务，跳过第二次模型改写"},
                )
                metrics.inc(
                    "kiwi_agent_fast_path_total", {"tool": fast_action["tool"]}
                )
                raw = json.dumps(
                    {
                        "thought": fast_action.get("thought") or "",
                        "plan": [],
                        "action": {
                            "tool": fast_action["tool"],
                            "args": fast_action["args"],
                            "summary": fast_action.get("summary") or "",
                            "step": fast_action.get("step"),
                        },
                        "answer": None,
                    },
                    ensure_ascii=False,
                )
                reply = AgentReply(
                    thought=str(fast_action.get("thought") or ""),
                    action={
                        "tool": fast_action["tool"],
                        "args": fast_action["args"],
                        "summary": fast_action.get("summary") or "",
                        "step": fast_action.get("step"),
                    },
                    raw=raw,
                )
            else:
                _model_started = time.perf_counter()
                try:
                    raw = await _complete(ctx)
                except Exception as exc:
                    _model_elapsed = time.perf_counter() - _model_started
                    trace.event(
                        "model",
                        ctx.model_name,
                        ms=_model_elapsed * 1000,
                        ok=False,
                        detail=type(exc).__name__,
                        input={
                            "messages": _history(ctx.messages),
                            "model": ctx.model_name,
                            "temperature": ctx.temperature,
                        },
                        output={"error": str(exc)[:2000]},
                        meta={
                            "model": ctx.model_name,
                            "attempts": max(1, ctx.last_attempts),
                            "error": type(exc).__name__,
                        },
                    )
                    metrics.observe(
                        "kiwi_agent_model_seconds",
                        _model_elapsed,
                        {"model": ctx.model_name, "ok": "false"},
                    )
                    metrics.inc(
                        "kiwi_agent_model_errors_total",
                        {"error": type(exc).__name__},
                    )
                    raise
                _model_elapsed = time.perf_counter() - _model_started
                tokens = ctx.last_usage.get("total_tokens", 0)
                trace.event(
                    "model",
                    ctx.model_name,
                    ms=_model_elapsed * 1000,
                    detail=f"chars={len(raw)}" + (f" · {tokens} tokens" if tokens else ""),
                    input={
                        "messages": _history(ctx.messages),
                        "model": ctx.model_name,
                        "temperature": ctx.temperature,
                    },
                    output=raw,
                    meta={
                        "model": ctx.model_name,
                        "temperature": ctx.temperature,
                        "usage": ctx.last_usage,
                        "finish_reason": ctx.last_finish_reason,
                        "attempts": ctx.last_attempts,
                    },
                )
                metrics.observe(
                    "kiwi_agent_model_seconds",
                    _model_elapsed,
                    {"model": ctx.model_name, "ok": "true"},
                )
                reply = _parse_reply_with_dsml(raw)
            if reply.action is None and _DSML_MARKER_RE.search(raw):
                # 原生工具调用标记既不是回答也不是合法协议；要求模型改写。
                if native_retries < 2:
                    native_retries += 1
                    trace.event(
                        "retry",
                        "原生工具调用格式",
                        ok=False,
                        detail="要求模型按 JSON 协议重写",
                        input={"raw": raw},
                        output={"attempt": native_retries},
                        meta={"reason": "dsml_or_native_tool_call"},
                    )
                    ctx.messages.append({"role": "assistant", "content": raw})
                    ctx.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "上一条回复使用了原生工具调用标记（如 <｜｜DSML｜｜>），"
                                "Kiwi 无法执行。请严格只返回一个 JSON 对象："
                                '{"thought":"…","plan":["…"],"action":{"tool":"…",'
                                '"args":{…},"summary":"…"},"answer":null}。'
                                "不要使用任何 XML / DSML / 函数调用标记，也不要把工具参数"
                                "写在 JSON 之外。"
                            ),
                        }
                    )
                    yield "notice", {"message": "模型返回的工具调用格式无效，正在重新生成"}
                    continue
                yield "chunk", {
                    "text": "模型连续返回了无法解析的工具调用格式，本轮已中止。请重试，"
                    "或在「设置 → 模型」中换一个模型。"
                }
                yield "done", {"ok": False, "plan": plan}
                return
            if reply.plan and not plan:
                plan = _normalize_plan(reply.plan)
                yield "plan", {"steps": plan, "thought": reply.thought}
            action = reply.action
            if action is None:
                if not reply.answer:
                    raise AgentFormatError("模型既没有给出工具调用，也没有给出回答")
                if answer_echoes_prompt(reply.answer, protocol_prompt):
                    if leak_retries < 1:
                        leak_retries += 1
                        trace.event(
                            "retry",
                            "回答复述系统提示",
                            ok=False,
                            detail="要求模型删除内部说明后重写",
                            input=reply.answer,
                            meta={"reason": "prompt_leak"},
                        )
                        ctx.messages.append(
                            {"role": "assistant", "content": reply.raw or raw}
                        )
                        ctx.messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "上一条回答混入了系统提示里的工具清单 / 权限 / 日期等内部文字，"
                                    "用户看不懂。请删除这些内容，只依据工具读取到的笔记原文或资料"
                                    "重新回答；材料不足就直接说明。不要复述任何系统提示。"
                                ),
                            }
                        )
                        yield "notice", {"message": "回答混入了系统内部说明，正在重新整理"}
                        continue
                    # 重试后仍然混入系统内容：宁可不展示，也不把不可读的回答交给用户。
                    yield "chunk", {
                        "text": "这次回答混入了系统内部说明，已中止。请重新提问，或明确指定要整理的笔记。"
                    }
                    yield "done", {"ok": False, "plan": plan}
                    return
                if plan:
                    _finalize_plan(plan)
                    yield "plan", {"steps": plan, "thought": reply.thought}
                yield "stage", {"stage": "agent", "status": "done", "message": "已完成思考"}
                yield "stage", {"stage": "generate", "status": "start", "message": "正在整理回答"}
                answer_text = _repair_note_links(reply.answer, known_links)
                trace.event(
                    "answer",
                    "最终回答",
                    input={
                        "model": ctx.model_name,
                        "citations": len(ctx.citations),
                    },
                    output=answer_text,
                    meta={"chars": len(answer_text)},
                )
                yield "chunk", {"text": answer_text}
                yield "stage", {"stage": "generate", "status": "done", "message": "回答生成完成"}
                yield "done", {"ok": True, "plan": plan, **_undo_fields(undo_record)}
                return

            tool = action["tool"]
            summary = action.get("summary") or ""
            try:
                args, label, summary, arg_labels = toolbox.prepare_call(
                    tool, action.get("args") or {}, summary, can_write=can_write
                )
            except agent_tools.ToolError as e:
                # 参数错误 / 越权：把错误反馈给模型，让它修正，不计入工具步数。
                ctx.messages.append(
                    {"role": "assistant", "content": reply.raw or raw}
                )
                ctx.messages.append(
                    {"role": "user", "content": f"工具调用未能执行：{e}\n请修正后重试。"}
                )
                yield "notice", {"message": f"已拦截一次无效工具调用：{e}"}
                continue

            tool_steps += 1
            read_only = toolbox.get(tool).read_only
            if plan and action.get("step") is not None:
                _mark_plan(plan, action.get("step"), "active")
                yield "plan", {"steps": plan, "thought": reply.thought}
            yield "tool_call", {
                "tool": tool,
                "label": label,
                "args": args,
                "read_only": read_only,
                "summary": summary,
            }
            yield "stage", {
                "stage": f"tool-{tool_steps}",
                "status": "start",
                "message": f"正在调用：{label}",
                "detail": summary,
            }

            if not read_only:
                pending = agent_actions.PendingAction(
                    tool=tool,
                    args=args,
                    summary=summary,
                    label=label,
                    messages=[dict(item) for item in ctx.messages],
                    assistant_content=reply.raw or raw,
                    plan=[dict(step) for step in plan],
                    kb_id=str(ctx.kb_id) if ctx.kb_id else None,
                    kb_ids=[str(item) for item in ctx.kb_ids],
                    scope_mode=ctx.scope_mode,
                    llm_config_id=str(ctx.llm_config_id) if ctx.llm_config_id else None,
                    model_override=ctx.model_override,
                    intent=ctx.intent,
                    citations=[citation.model_dump(mode="json") for citation in ctx.citations],
                    arg_labels=arg_labels,
                )
                agent_actions.store(pending)
                trace.event(
                    "approval",
                    label,
                    detail=summary,
                    input=pending.payload(),
                    output={"awaiting_approval": True},
                    meta={"tool": tool},
                )
                metrics.inc("kiwi_agent_approvals_total", {"tool": tool})
                if plan and action.get("step") is not None:
                    _mark_plan(plan, action.get("step"), "pending")
                    yield "plan", {"steps": plan, "thought": reply.thought}
                yield "stage", {
                    "stage": f"tool-{tool_steps}",
                    "status": "done",
                    "message": f"等待确认：{label}",
                    "detail": summary,
                }
                yield "approval", pending.payload()
                yield "done", {
                    "ok": True,
                    "awaiting_approval": True,
                    "action_id": pending.id,
                }
                return

            _tool_started = time.perf_counter()
            try:
                result = await toolbox.execute(session, ctx.kb_id, tool, args)
                ok = True
                error = ""
            except agent_tools.ToolError as e:
                result = {"ok": False, "error": str(e)}
                ok = False
                error = str(e)
            _tool_elapsed = time.perf_counter() - _tool_started
            trace.event(
                "tool",
                tool,
                ms=_tool_elapsed * 1000,
                ok=ok,
                detail=summary,
                input={"tool": tool, "args": args},
                output=_tool_result_ui(result),
                meta={"read_only": True, "summary": summary},
            )
            metrics.observe(
                "kiwi_agent_tool_seconds",
                _tool_elapsed,
                {"tool": tool, "ok": str(ok).lower()},
            )
            _collect_link_targets(result, known_links)
            if plan and action.get("step") is not None:
                _mark_plan(plan, action.get("step"), "done" if ok else "pending")
                yield "plan", {"steps": plan, "thought": reply.thought}
            yield "tool_result", {
                "tool": tool,
                "label": label,
                "ok": ok,
                "summary": summary if ok else error,
                "data": _tool_result_ui(result),
            }
            yield "stage", {
                "stage": f"tool-{tool_steps}",
                "status": "done" if ok else "error",
                "message": f"{label}{'完成' if ok else '失败'}",
                "detail": "" if ok else error,
            }
            ctx.messages.append(
                {"role": "assistant", "content": reply.raw or raw}
            )
            ctx.messages.append(
                {
                    "role": "user",
                    "content": (
                        f"工具 {tool} 的执行结果：\n{_tool_result_text(result)}\n\n"
                        "请根据结果继续。若已获得足够信息，"
                        '返回 {"action": null, "answer": "..."}。'
                    ),
                }
            )
            # 第二轮模型调用可能很慢（例如要把整页正文整理成新建笔记的参数）。
            # 更新阶段文案，避免界面一直停在「正在分析并规划操作」，让用户知道
            # 读取已完成、当前在等模型生成后续操作。
            if ok:
                yield "stage", {
                    "stage": "agent",
                    "status": "start",
                    "message": (
                        "已读取网页，正在整理内容并生成操作"
                        if tool == "fetch_url"
                        else f"已获取「{label}」结果，正在继续分析"
                    ),
                }
            else:
                yield "stage", {
                    "stage": "agent",
                    "status": "start",
                    "message": "工具执行失败，正在让模型调整方案",
                }
            if ok and tool in ("fetch_url", "get_template"):
                fast_tool = tool
                fast_result = result

        # 达到工具调用上限：再给模型一次只回答、不调工具的机会。
        ctx.messages.append(
            {
                "role": "user",
                "content": (
                    "已达到工具调用上限。请不要再调用工具，直接返回 "
                    '{"action": null, "answer": "..."}，总结已完成与未完成的部分。'
                ),
            }
        )
        raw = await _complete(ctx)
        reply = _parse_reply_with_dsml(raw)
        # 原生工具调用标记不能当回答展示；这里只接受普通文本回答。
        answer_text = "" if _DSML_MARKER_RE.search(raw) else reply.answer
        answer = _repair_note_links(answer_text or "", known_links) or (
            "已达到最大工具调用步数，请补充更具体的要求后重试。"
        )
        if plan:
            _finalize_plan(plan)
            yield "plan", {"steps": plan, "thought": reply.thought}
        yield "stage", {"stage": "agent", "status": "done", "message": "已达到工具调用上限"}
        trace.event(
            "answer",
            "最终回答（步数上限）",
            output=answer,
            meta={"chars": len(answer), "step_limit": True},
        )
        yield "chunk", {"text": answer}
        yield "done", {
            "ok": True,
            "plan": plan,
            "step_limit": True,
            **_undo_fields(undo_record),
        }
    except (agent_tools.ToolError,) as e:
        trace.event(
            "error",
            type(e).__name__,
            ok=False,
            detail=str(e),
            output={"error": str(e)},
        )
        yield "error", {"message": str(e)}
    except AgentFormatError as e:
        trace.event(
            "error",
            type(e).__name__,
            ok=False,
            detail=str(e),
            output={"error": str(e)},
        )
        yield "error", {"message": f"Agent 响应格式不正确：{e}"}
    except Exception as e:  # noqa: BLE001 —— SSE 已开始，只能通知前端
        # 写操作已经落库，只是后续模型总结失败：不能报“执行失败”让用户误以为
        # 没保存。给出确定性的完成回执与真实笔记链接。
        if last_write is not None and isinstance(
            e, (APIConnectionError, APITimeoutError, APIStatusError, asyncio.TimeoutError)
        ):
            label, _result = last_write
            links = "、".join(
                f"[{title}](kiwi://note/{note_id})"
                for note_id, title in known_links.items()
            )
            suffix = f" 已完成：{links}。" if links else ""
            trace.event(
                "fallback",
                label,
                detail="模型总结中断，返回确定性回执",
                input={"label": label},
                output={"links": links, "error": type(e).__name__},
                meta={"error": str(e)[:1000]},
            )
            yield "chunk", {
                "text": (
                    f"{label}已执行完成，但模型连接中断，未能生成总结。"
                    f"{suffix}请在笔记列表确认结果。"
                )
            }
            _finalize_plan(plan)
            if plan:
                yield "plan", {"steps": plan, "thought": "操作已完成"}
            yield "stage", {
                "stage": "generate",
                "status": "done",
                "message": "操作完成（模型总结中断）",
            }
            yield "done", {"ok": True, "plan": plan, **_undo_fields(undo_record)}
            return
        trace.event(
            "error",
            type(e).__name__,
            ok=False,
            detail=str(e),
            output={"error": str(e)},
            meta={"error": type(e).__name__},
        )
        logger.exception("Agent 循环失败")
        yield "error", {"message": f"Agent 执行失败：{e}"}
    finally:
        has_error = any(event["kind"] == "error" for event in trace.events)
        has_approval = any(event["kind"] == "approval" for event in trace.events)
        status = (
            "error"
            if has_error
            else ("awaiting_approval" if has_approval else "done")
        )
        trace.finish(status)
        metrics.inc("kiwi_agent_turns_total", {"status": status})


__all__ = [
    "AgentContext",
    "AgentReply",
    "build_messages",
    "parse_reply",
    "run_agent",
]
