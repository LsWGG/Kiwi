"""Agent 每轮轨迹：span 结构 + 输入 / 输出 / token 使用量。

设计参考 LangSmith / Langfuse 一类 LLMOps 工具的 trace view：

- 一轮问答是一条 trace，规划、每次模型调用、工具执行、审批与最终回答是 span；
- span 保存输入（消息数组 / 工具参数）、输出（模型原文 / 工具结果）、
  元数据（token、finish_reason、重试次数）与耗时；
- 只在内存环形缓冲保留最近 100 轮，重启即清空，不写数据库；
- 内容按字段截断，常见凭据键名（api_key / authorization / token 等）做脱敏。

端口只挂在受访问令牌保护的 /api 运维页；如果未来要落到数据库，需要先补
保留期、采样与更严格的脱敏规则。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

MAX_EVENTS = 80
MAX_TRACES = 100
MAX_CONTENT_CHARS = 4000
MAX_PAYLOAD_CHARS = 24_000
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|secret|password|access[_-]?token|"
    r"refresh[_-]?token|fernet[_-]?key)$",
    re.IGNORECASE,
)

_buffer: deque["AgentTrace"] = deque(maxlen=MAX_TRACES)
_lock = threading.Lock()


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "…（层级过深）"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                out[key] = "***"
            else:
                out[key] = _sanitize(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [_sanitize(item, depth + 1) for item in list(value)[:50]]
        if len(value) > 50:
            items.append(f"…（另有 {len(value) - 50} 项）")
        return items
    if isinstance(value, str):
        if len(value) > MAX_CONTENT_CHARS:
            return value[:MAX_CONTENT_CHARS] + "…（轨迹已截断）"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_CONTENT_CHARS]


def _budget(value: Any) -> Any:
    """限制单个 span 输入 / 输出的总 JSON 体积；超出时保留可读预览。"""
    if value is None:
        return None
    clean = _sanitize(value)
    text = json.dumps(clean, ensure_ascii=False, default=str)
    if len(text) <= MAX_PAYLOAD_CHARS:
        return clean
    return {
        "_truncated": True,
        "chars": len(text),
        "preview": text[:MAX_PAYLOAD_CHARS] + "…",
    }


@dataclass
class AgentTrace:
    id: str
    started_at: float
    query: str
    query_chars: int
    model: str
    scope: str
    planner_source: str = ""
    planner_ms: float = 0.0
    planner_queries: int = 0
    status: str = "running"
    finished_at: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def event(
        self,
        kind: str,
        name: str,
        *,
        ms: float = 0.0,
        ok: bool = True,
        detail: str = "",
        input: Any = None,
        output: Any = None,
        meta: Any = None,
    ) -> None:
        payload: dict[str, Any] = {
            "at": round(time.time() - self.started_at, 3),
            "kind": kind[:20],
            "name": str(name or "")[:120],
            "ms": int(max(0.0, ms)),
            "ok": bool(ok),
            "detail": str(detail or "")[:400],
        }
        input_value = _budget(input)
        output_value = _budget(output)
        meta_value = _budget(meta)
        if input_value is not None:
            payload["input"] = input_value
        if output_value is not None:
            payload["output"] = output_value
        if meta_value is not None:
            payload["meta"] = meta_value
        self.events.append(payload)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]

    def finish(self, status: str) -> None:
        if self.finished_at is None:
            self.finished_at = time.time()
            self.status = status

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": int(
                ((self.finished_at or time.time()) - self.started_at) * 1000
            ),
            "status": self.status,
            "query": self.query,
            "query_chars": self.query_chars,
            "model": self.model,
            "scope": self.scope,
            "planner_source": self.planner_source,
            "planner_ms": int(self.planner_ms),
            "planner_queries": self.planner_queries,
            "events": list(self.events),
        }


def start_trace(
    *,
    query: str = "",
    query_chars: int | None = None,
    model: str,
    scope: str,
    planner_source: str = "",
    planner_ms: float = 0.0,
    planner_queries: int = 0,
    record: bool = True,
) -> AgentTrace:
    """创建一轮 trace；``record=False`` 时只随请求存在，不进入运维列表。"""
    text = str(query or "")
    trace = AgentTrace(
        id=uuid.uuid4().hex[:12],
        started_at=time.time(),
        query=text[:MAX_CONTENT_CHARS],
        query_chars=(
            len(text) if query_chars is None else max(0, int(query_chars))
        ),
        model=str(model or "")[:120],
        scope=str(scope or "")[:20],
        planner_source=str(planner_source or "")[:20],
        planner_ms=max(0.0, float(planner_ms)),
        planner_queries=max(0, int(planner_queries)),
    )
    if record:
        with _lock:
            _buffer.appendleft(trace)
    return trace


def recent(limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        traces = list(_buffer)[: max(1, min(limit, MAX_TRACES))]
    return [trace.payload() for trace in traces]


def get(trace_id: str) -> dict[str, Any] | None:
    """按 ID 取单条 trace；超出保留窗口后返回 None。"""
    wanted = str(trace_id or "").strip()
    if not wanted:
        return None
    with _lock:
        for trace in _buffer:
            if trace.id == wanted:
                return trace.payload()
    return None


def clear() -> None:
    with _lock:
        _buffer.clear()


__all__ = ["AgentTrace", "MAX_TRACES", "clear", "get", "recent", "start_trace"]
