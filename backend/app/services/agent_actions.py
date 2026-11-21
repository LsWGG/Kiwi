"""Agent 写操作的待确认队列（仅进程内存储）。

不新增数据库表：待确认动作 15 分钟过期，服务重启或过期后前端会提示重新
提问。一次确认只能消费一次（``claim`` 原子弹出），避免重复执行。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

TTL_SECONDS = 15 * 60
MAX_PENDING = 32


@dataclass
class PendingAction:
    tool: str
    args: dict[str, Any]
    summary: str
    label: str
    messages: list[dict]
    assistant_content: str
    plan: list[dict]
    kb_id: str | None
    kb_ids: list[str]
    scope_mode: str
    llm_config_id: str | None
    model_override: str | None
    intent: str
    citations: list[dict] = field(default_factory=list)
    # 参数名到中文标签，由工具注册表提供，前端审批卡片不再维护硬编码映射。
    arg_labels: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + TTL_SECONDS)

    def payload(self) -> dict[str, Any]:
        return {
            "action_id": self.id,
            "tool": self.tool,
            "label": self.label,
            "summary": self.summary,
            "args": self.args,
            "arg_labels": self.arg_labels,
            "expires_at": int(self.expires_at),
        }


_lock = threading.Lock()
_actions: dict[str, PendingAction] = {}


def _purge_locked(now: float | None = None) -> None:
    current = time.time() if now is None else now
    expired = [key for key, action in _actions.items() if action.expires_at <= current]
    for key in expired:
        _actions.pop(key, None)


def store(action: PendingAction) -> PendingAction:
    """登记待确认动作；超过上限时淘汰最早的一条。"""
    with _lock:
        _purge_locked()
        while len(_actions) >= MAX_PENDING:
            oldest = min(_actions.values(), key=lambda item: item.created_at)
            _actions.pop(oldest.id, None)
        _actions[action.id] = action
    return action


def claim(action_id: str) -> PendingAction | None:
    """取出并删除动作，保证同一次批准只执行一次。"""
    if not action_id:
        return None
    with _lock:
        _purge_locked()
        return _actions.pop(action_id, None)


def peek(action_id: str) -> PendingAction | None:
    with _lock:
        _purge_locked()
        return _actions.get(action_id)


def clear() -> None:
    """测试辅助：清空待确认队列。"""
    with _lock:
        _actions.clear()


__all__ = [
    "MAX_PENDING",
    "TTL_SECONDS",
    "PendingAction",
    "claim",
    "clear",
    "peek",
    "store",
]
