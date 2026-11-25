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


async def test_prepare_chat_skips_retrieval_for_smalltalk(monkeypatch):
    """规划器判断无需资料时，不检索、不同步索引、不联网。"""
    from app.services import agent_trace
    from app.services.agent_planner import AgentPlan

    agent_trace.clear()
    calls: list[str] = []

    async def fake_resolve_scope(session, scope):
        return []

    async def fake_resolve_llm(session, kb_id, llm_config_id=None):
        return (
            SimpleNamespace(
                base_url="http://127.0.0.1:9", model_name="m", extra_params={}
            ),
            "",
        )

    async def fake_plan(*args, **kwargs):
        return AgentPlan(
            queries=[],
            needs_retrieval=False,
            reason="打招呼无需资料",
            source="llm",
        )

    async def fake_search(*args, **kwargs):
        calls.append("search")
        return [], ""

    async def fake_index(*args, **kwargs):
        calls.append("index")

    monkeypatch.setattr(chat, "_resolve_scope", fake_resolve_scope)
    monkeypatch.setattr(chat, "resolve_llm", fake_resolve_llm)
    monkeypatch.setattr(chat, "_plan_request", fake_plan)
    monkeypatch.setattr(chat, "_safe_search_many", fake_search)
    monkeypatch.setattr(chat, "ensure_notes_indexed", fake_index)

    stages: list[tuple] = []
    prepared = await chat._prepare_chat(
        None,
        ChatRequest(messages=[{"role": "user", "content": "你好"}], agent=True),
        "你好",
        "note",
        lambda *args: stages.append(args),
    )
    assert calls == []
    assert all(stage[0] not in ("search", "index", "web") for stage in stages)
    assert ("plan", "done", "无需检索资料", "打招呼无需资料") in stages
    system = prepared.openai_msgs[0]["content"]
    assert "无需检索知识库或联网资料" in system
    assert "资料：" not in system

    trace = prepared.trace
    assert trace is not None
    kinds = [event["kind"] for event in trace.events]
    assert "understand" in kinds and "planner" in kinds
    assert all(
        event["name"] not in ("检索 Wiki", "检索笔记", "同步笔记索引", "联网检索")
        for event in trace.events
    )
    trace.finish("done")
    agent_trace.clear()


async def test_stream_emits_stages_notice_citation_chunks_done(monkeypatch):
    fake_client = _FakeClient([_delta("你"), _delta("好")])
    notice = "知识库检索暂时不可用，本次将基于联网结果或对话上下文回答。"

    async def fake_prepare(session, data, query, intent, stage, *, trace=None, on_plan=None):
        stage("understand", "start", "正在理解问题")
        stage("search", "start", "正在检索 Wiki 与笔记")
        stage("search", "done", "知识库检索完成", "命中 0 个片段")
        if on_plan is not None:
            on_plan(["检查资料", "整理回答"])
        return _prepared(fake_client, intent, [notice])

    monkeypatch.setattr(chat, "_prepare_chat", fake_prepare)
    monkeypatch.setattr(chat, "is_disabled", lambda: False)

    resp = await chat_stream(
        ChatRequest(messages=[{"role": "user", "content": "测试问题"}], intent="wiki"),
        session=None,
    )
    events = _parse_events(await _collect(resp))

    names = [name for name, _ in events]
    assert names[:4] == ["stage", "stage", "stage", "plan"]
    assert [step["title"] for step in events[3][1]["steps"]] == [
        "检查资料",
        "整理回答",
    ]
    assert events[0][1] == {
        "stage": "understand",
        "status": "start",
        "message": "正在理解问题",
        "detail": "",
    }
    assert names[4] == "notice"
    assert events[4][1] == {"message": notice}
    assert names[5] == "citation"
    assert events[5][1]["intent"] == "wiki"
    assert events[5][1]["citations"][0]["title"] == "测试页面"
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
    async def fake_prepare(session, data, query, intent, stage, *, trace=None, on_plan=None):
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
    async def fake_prepare(session, data, query, intent, stage, *, trace=None, on_plan=None):
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


async def test_prepare_chat_runs_wiki_and_note_retrieval_concurrently(monkeypatch):
    """Wiki 与笔记检索应在同一时间窗口内执行，而不是前后排队。"""
    import asyncio

    from app.services.agent_planner import AgentPlan

    started: list[str] = []
    both_started = asyncio.Event()

    async def fake_scope(session, scope):
        return []

    async def fake_resolve_llm(session, kb_id, llm_config_id=None):
        return (
            SimpleNamespace(
                base_url="http://127.0.0.1:9", model_name="m", extra_params={}
            ),
            "",
        )

    async def fake_plan(*args, **kwargs):
        return AgentPlan(
            queries=["问题"], needs_retrieval=True, source="llm", steps=[]
        )

    async def fake_context(session, kb_ids, collection, filters=None):
        return {}, None

    async def fake_index(kb_ids):
        return None

    async def fake_search(session, queries, kb_ids, *, collection, **kwargs):
        started.append(collection)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return [], ""

    monkeypatch.setattr(chat, "_resolve_scope", fake_scope)
    monkeypatch.setattr(chat, "resolve_llm", fake_resolve_llm)
    monkeypatch.setattr(chat, "_plan_request", fake_plan)
    monkeypatch.setattr(chat, "prepare_search_context", fake_context)
    monkeypatch.setattr(chat, "ensure_notes_indexed", fake_index)
    monkeypatch.setattr(chat, "_safe_search_many", fake_search)
    monkeypatch.setattr(chat, "is_remote_provider", lambda: False)
    monkeypatch.setattr(chat.llm_factory, "get_client", lambda *a, **k: SimpleNamespace())

    prepared = await chat._prepare_chat(
        None,
        ChatRequest(messages=[{"role": "user", "content": "问题"}], agent=True),
        "问题",
        "note",
        lambda *args: None,
    )
    assert started == ["wiki", "note"] or sorted(started) == ["note", "wiki"]
    assert prepared.planner_queries == 1
