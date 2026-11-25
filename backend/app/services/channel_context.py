"""外部渠道上下文。

Agent 工具在微信等渠道里需要知道「是谁在提问」才能创建定时推送，
但工具的签名保持 ``(session, kb_id, args)`` 不变，避免影响 Web 问答。
这里用 ContextVar 在调用 Agent 前注入，任务结束后自动恢复。
"""

from __future__ import annotations

from contextvars import ContextVar

# 当前微信发送者 ID（xxx@im.wechat）；Web 问答时为空。
current_wechat_sender: ContextVar[str] = ContextVar(
    "kiwi_wechat_sender", default=""
)
# 当前微信会话绑定的知识库 ID；Web 问答时为空。
current_wechat_kb_id: ContextVar[str] = ContextVar(
    "kiwi_wechat_kb_id", default=""
)

__all__ = ["current_wechat_kb_id", "current_wechat_sender"]
