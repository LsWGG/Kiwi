"""问答流式阶段反馈：检索降级、stage/notice 事件顺序与错误收尾。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import HTTPException

from app.routers import chat
from app.routers.chat import (
    ChatRequest,
    Citation,
    _PreparedChat,
    _safe_search_many,
    chat_stream,
)


async def test_safe_search_many_degrades_on_vector_failure(monkeypatch):
    """Qdrant 超时（如 408）不应让整个问答 500。"""

    async def boom(*args, **kwargs):
        raise RuntimeError("Unexpected Response: 408 (Request Timeout)")

    monkeypatch.setattr(chat, "_search_many", boom)
    hits, notice = await _safe_search_many(
        None, ["问题"], [], limit=4, collection="wiki"
    )
    assert hits == []
    assert "知识库检索暂时不可用" in notice


def _parse_events(raw: str) -> list[tuple[str, dict]]:
    """把 SSE 文本拆成 (event, payload)，忽略 keepalive 注释帧。"""
    events: list[tuple[str, dict]] = []
    for frame in raw.split("\n\n"):
        frame = frame.strip()
        if not frame or frame.startswith(":"):
            continue
        lines = dict(
            line.split(": ", 1) for line in frame.splitlines() if ": " in line
        )
        if "event" in lines and "data" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def _delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


class _FakeStream:
    def __init__(self, chunks: list[SimpleNamespace]):
        self._chunks = iter(chunks)

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


class _FakeClient:
    """只实现 chat.completions.create 的流式接口。"""

    def __init__(self, chunks: list[SimpleNamespace]):
        self._chunks = chunks
        self.kwargs: dict = {}
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeStream(self._chunks)


def _prepared(client: _FakeClient, intent: str, notices: list[str]) -> _PreparedChat:
    return _PreparedChat(
        openai_msgs=[{"role": "system", "content": "资料"}],
        citations=[Citation(collection="wiki", title="测试页面")],
        intent=intent,
        cfg=SimpleNamespace(extra_params={}),
        client=client,
        model_name="test-model",
        notices=notices,
    )


async def _collect(resp) -> str:
    raw = ""
    async for piece in resp.body_iterator:
        raw += piece.decode() if isinstance(piece, bytes) else piece
    return raw


async def test_stream_emits_stages_notice_citation_chunks_done(monkeypatch):
    fake_client = _FakeClient([_delta("你"), _delta("好")])
    notice = "知识库检索暂时不可用，本次将基于联网结果或对话上下文回答。"

    async def fake_prepare(session, data, query, intent, stage):
        stage("understand", "start", "正在理解问题")
        stage("search", "start", "正在检索 Wiki 与笔记")
        stage("search", "done", "知识库检索完成", "命中 0 个片段")
        return _prepared(fake_client, intent, [notice])

    monkeypatch.setattr(chat, "_prepare_chat", fake_prepare)
    monkeypatch.setattr(chat, "is_disabled", lambda: False)

    resp = await chat_stream(
        ChatRequest(messages=[{"role": "user", "content": "测试问题"}], intent="wiki"),
        session=None,
    )
    events = _parse_events(await _collect(resp))

    names = [name for name, _ in events]
    assert names[:3] == ["stage", "stage", "stage"]
    assert events[0][1] == {
        "stage": "understand",
        "status": "start",
        "message": "正在理解问题",
        "detail": "",
    }
    assert names[3] == "notice"
    assert events[3][1] == {"message": notice}
    assert names[4] == "citation"
    assert events[4][1]["intent"] == "wiki"
    assert events[4][1]["citations"][0]["title"] == "测试页面"
    assert [payload["text"] for name, payload in events if name == "chunk"] == [
        "你",
        "好",
    ]
    assert names[-2:] == ["stage", "done"]
    assert events[-2][1]["stage"] == "generate"
    assert events[-2][1]["status"] == "done"
    assert events[-1][1] == {"ok": True}
    assert fake_client.kwargs["model"] == "test-model"
    assert fake_client.kwargs["stream"] is True


async def test_stream_reports_prepare_failure_as_sse_error(monkeypatch):
    async def fake_prepare(session, data, query, intent, stage):
        raise HTTPException(400, "未配置大模型连接，请先在设置中添加并设为默认。")

    monkeypatch.setattr(chat, "_prepare_chat", fake_prepare)
    monkeypatch.setattr(chat, "is_disabled", lambda: False)

    resp = await chat_stream(
        ChatRequest(messages=[{"role": "user", "content": "测试问题"}], intent="note"),
        session=None,
    )
    events = _parse_events(await _collect(resp))

    assert [name for name, _ in events] == ["error"]
    assert "未配置大模型连接" in events[0][1]["message"]


async def test_stream_reports_unexpected_prepare_error(monkeypatch):
    async def fake_prepare(session, data, query, intent, stage):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat, "_prepare_chat", fake_prepare)
    monkeypatch.setattr(chat, "is_disabled", lambda: False)

    resp = await chat_stream(
        ChatRequest(messages=[{"role": "user", "content": "测试问题"}], intent="wiki"),
        session=None,
    )
    events = _parse_events(await _collect(resp))

    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["message"] == "检索资料时出现异常，请稍后重试。"
