"""微信 ClawBot 渠道：iLink 请求结构、问答路由、确认与主动推送。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from app.services import wechat_clawbot
from app.services.channel_context import current_wechat_sender
from app.services.wechat_clawbot import ChatResult, WeChatChannel, WeChatStore


def _channel(tmp_path: Path) -> WeChatChannel:
    channel = WeChatChannel()
    channel.store = WeChatStore(tmp_path / "wechat.json")
    channel._token = "test-token"
    channel._base_url = "https://ilink.test"
    return channel


def _client(channel: WeChatChannel, handler):
    channel._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return channel


async def test_store_encrypts_token_and_status_hides_it(tmp_path, monkeypatch):
    channel = _channel(tmp_path)
    channel._token = ""
    await channel.store.update(
        lambda state: state.update(
            {
                "enabled": True,
                "allowed_users": ["u@im.wechat"],
                "default_kb_id": str(uuid.uuid4()),
                "bot_token": wechat_clawbot._encrypt_token("secret-token"),
            }
        )
    )
    status = await channel.full_status()
    assert status["connected"] is False  # 内存 token 未设置
    assert "secret-token" not in json.dumps(status)


async def test_send_message_uses_required_ilink_payload(tmp_path):
    channel = _channel(tmp_path)
    calls: list[dict] = []

    async def handler(request: httpx.Request):
        calls.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"ret": 0})

    _client(channel, handler)
    try:
        assert await channel._send_message(
            "u@im.wechat", "ctx-token", "你好"
        )
    finally:
        await channel._http.aclose()
    payload = calls[0]
    msg = payload["msg"]
    assert msg["to_user_id"] == "u@im.wechat"
    assert msg["context_token"] == "ctx-token"
    assert msg["message_type"] == 2
    assert msg["message_state"] == 2
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "你好"}}]
    assert payload["base_info"]["channel_version"] == wechat_clawbot.CHANNEL_VERSION


async def test_allowed_user_question_replies_and_updates_history(
    tmp_path, monkeypatch
):
    channel = _channel(tmp_path)
    agent_calls: list[list[dict]] = []

    async def fake_chat(messages, kb_id, sender, **kwargs):
        agent_calls.append(messages)
        return ChatResult(answer="这是回答")

    async def noop_typing(*args, **kwargs):
        return None

    monkeypatch.setattr(channel, "_run_chat", fake_chat)
    monkeypatch.setattr(channel, "_send_typing", noop_typing)
    sent: list[str] = []

    async def fake_send(sender, token, text):
        sent.append(text)
        return True

    monkeypatch.setattr(channel, "send_reply", fake_send)
    kb_id = uuid.uuid4()
    await channel.store.update(
        lambda state: state.update(
            {
                "enabled": True,
                "allowed_users": ["u@im.wechat"],
                "default_kb_id": str(kb_id),
                "contacts": {
                    "u@im.wechat": {
                        "context_token": "ctx",
                        "at": wechat_clawbot._now(),
                    }
                },
            }
        )
    )
    await channel._handle_message_locked("u@im.wechat", "这周我干嘛了？", "ctx")
    assert sent == ["这是回答"]
    assert agent_calls and agent_calls[0][-1]["content"] == "这周我干嘛了？"
    data = await channel.store.read()
    history = data["history"]["u@im.wechat"]
    assert [item["role"] for item in history] == ["user", "assistant"]


async def test_write_approval_needs_confirm_then_resumes(tmp_path, monkeypatch):
    channel = _channel(tmp_path)
    calls: list[dict] = []

    async def fake_chat(messages, kb_id, sender, **kwargs):
        calls.append(kwargs)
        if kwargs.get("resume_action_id"):
            return ChatResult(answer="已创建笔记")
        return ChatResult(
            approval={
                "action_id": "act-1",
                "label": "新建笔记",
                "summary": "新建笔记《测试》",
            }
        )

    async def noop_typing(*args, **kwargs):
        return None

    monkeypatch.setattr(channel, "_run_chat", fake_chat)
    monkeypatch.setattr(channel, "_send_typing", noop_typing)
    sent: list[str] = []

    async def fake_send(sender, token, text):
        sent.append(text)
        return True

    monkeypatch.setattr(channel, "send_reply", fake_send)
    await channel.store.update(
        lambda state: state.update(
            {
                "enabled": True,
                "allowed_users": ["u@im.wechat"],
                "default_kb_id": str(uuid.uuid4()),
            }
        )
    )
    await channel._handle_message_locked("u@im.wechat", "帮我建一篇笔记", "ctx")
    assert "需要确认" in sent[0]
    pending = (await channel.store.read())["pending"]["u@im.wechat"]
    assert pending["action_id"] == "act-1"

    await channel._handle_message_locked("u@im.wechat", "确认", "ctx")
    assert calls[-1]["resume_action_id"] == "act-1"
    assert calls[-1]["approve"] is True
    assert sent[-1] == "已创建笔记"
    assert "u@im.wechat" not in (await channel.store.read())["pending"]


async def test_proactive_push_queues_when_window_expired(tmp_path):
    channel = _channel(tmp_path)
    await channel.store.update(
        lambda state: state.update(
            {
                "contacts": {
                    "u@im.wechat": {"context_token": "old", "at": 0}
                }
            }
        )
    )
    assert await channel.send_proactive("u@im.wechat", "早报") is False
    data = await channel.store.read()
    assert data["queued"]["u@im.wechat"][0]["text"] == "早报"

    sent: list[str] = []

    async def fake_send(sender, token, text):
        sent.append(text)
        return True

    channel.send_reply = fake_send  # type: ignore[method-assign]
    await channel._flush_queue("u@im.wechat", "new-ctx")
    assert sent and sent[0].startswith("[补发]")
    assert (await channel.store.read())["queued"] == {}


async def test_schedule_push_persists_and_filters_by_sender(tmp_path):
    channel = _channel(tmp_path)
    kb_id = str(uuid.uuid4())
    item = await channel.schedule_push(
        "u@im.wechat", [kb_id], "总结今天待办", "0 9 * * *"
    )
    assert item["cron"] == "0 9 * * *"
    assert item["kb_ids"] == [kb_id]
    assert (await channel.list_schedules())[0]["prompt"] == "总结今天待办"
    assert await channel.toggle_schedule(item["id"], False)
    assert (await channel.list_schedules())[0]["enabled"] is False
    assert await channel.delete_schedule(item["id"])
    assert await channel.list_schedules() == []


async def test_wechat_tool_requires_channel_sender(tmp_path, monkeypatch):
    from app.services import agent_tools

    channel = _channel(tmp_path)
    monkeypatch.setattr(wechat_clawbot, "channel", channel)
    token = current_wechat_sender.set("")
    try:
        with pytest.raises(agent_tools.ToolError, match="仅支持 ClawBot 渠道"):
            await agent_tools.execute_tool(
                object(),
                uuid.uuid4(),
                "schedule_wechat_push",
                {"schedule": "每天早上九点", "prompt": "待办"},
            )
    finally:
        current_wechat_sender.reset(token)


async def test_status_renews_login_while_polling_works(tmp_path):
    channel = _channel(tmp_path)
    now = wechat_clawbot._now()
    await channel.store.update(
        lambda state: state.update(
            {"login_at": now - 25 * 3600, "warning_sent_at": 0}
        )
    )
    channel._last_activity_at = now
    status = await channel.full_status()
    assert status["remaining_seconds"] > 23 * 3600


async def test_status_expires_without_activity(tmp_path):
    channel = _channel(tmp_path)
    now = wechat_clawbot._now()
    await channel.store.update(
        lambda state: state.update({"login_at": now - 25 * 3600})
    )
    status = await channel.full_status()
    assert status["remaining_seconds"] == 0


async def test_inbound_message_renews_login_time(tmp_path, monkeypatch):
    channel = _channel(tmp_path)
    sent: list[str] = []

    async def fake_send(sender, token, text):
        sent.append(text)
        return True

    monkeypatch.setattr(channel, "send_reply", fake_send)
    now = wechat_clawbot._now()
    await channel.store.update(
        lambda state: state.update(
            {"login_at": now - 25 * 3600, "warning_sent_at": 123}
        )
    )
    await channel._handle_message_locked("u@im.wechat", "/time", "ctx")
    data = await channel.store.read()
    assert data["login_at"] >= now - 5
    assert data["warning_sent_at"] == 0
    assert sent and "小时" in sent[0]
