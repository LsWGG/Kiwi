"""Agent harness：JSON 协议、只读自动执行、写操作确认与恢复。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.mcp import Toolbox
from app.services import (
    agent_actions,
    agent_fast_path,
    agent_harness,
    agent_tools,
)
from app.services.agent_planner import app_timezone


class _FakeCompletions:
    def __init__(self, replies: list[str]):
        self.replies = iter(replies)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        text = next(self.replies)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=text),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )


class _FakeClient:
    def __init__(self, replies: list[str]):
        self.completions = _FakeCompletions(replies)
        self.chat = SimpleNamespace(completions=self.completions)


def _reply(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _ctx(client: _FakeClient, *, scope_mode: str = "kb", kb_id: uuid.UUID | None = None) -> agent_harness.AgentContext:
    kb = kb_id or uuid.uuid4()
    return agent_harness.AgentContext(
        messages=[
            {"role": "system", "content": "资料"},
            {"role": "user", "content": "帮我整理笔记"},
        ],
        citations=[],
        intent="note",
        client=client,
        model_name="test-model",
        temperature=0.3,
        kb_id=kb,
        kb_ids=[kb],
        llm_config_id=None,
        model_override=None,
        scope_mode=scope_mode,
    )


async def _collect(ctx, session, **kwargs):
    return [event async for event in agent_harness.run_agent(ctx, session, **kwargs)]


@pytest.fixture(autouse=True)
def _clear_actions():
    agent_actions.clear()
    yield
    agent_actions.clear()


def test_parse_reply_accepts_fenced_and_plain_json():
    fenced = '```json\n{"thought":"想一想","plan":["查笔记"],"action":null,"answer":"好了"}\n```'
    reply = agent_harness.parse_reply(fenced)
    assert reply.thought == "想一想"
    assert reply.plan == ["查笔记"]
    assert reply.action is None
    assert reply.answer == "好了"

    plain = agent_harness.parse_reply("这不是 JSON，但可以当作回答")
    assert plain.answer.startswith("这不是 JSON")
    assert plain.action is None

    # 用户要求模型直接输出 JSON 时，业务 JSON 不应被当成 Agent 协议。
    business = '{"name": "kiwi", "retries": 3}'
    reply = agent_harness.parse_reply(business)
    assert reply.answer == business
    assert reply.action is None


def test_prepare_tool_call_blocks_writes_outside_single_kb():
    with pytest.raises(agent_tools.ToolError, match="单个知识库"):
        agent_tools.prepare_tool_call(
            "create_note",
            {"title": "测试"},
            "",
            can_write=False,
        )
    for tool, args in (
        ("update_folder", {"folder_id": str(uuid.uuid4()), "name": "新名称"}),
        ("delete_folder", {"folder_id": str(uuid.uuid4())}),
    ):
        assert tool not in agent_tools.READ_ONLY_TOOLS
        with pytest.raises(agent_tools.ToolError, match="单个知识库"):
            agent_tools.prepare_tool_call(tool, args, "", can_write=False)


def test_prepare_update_preserves_explicit_null():
    args, label, _summary = agent_tools.prepare_tool_call(
        "update_note",
        {"note_id": str(uuid.uuid4()), "folder_id": None},
        "",
        can_write=True,
    )
    assert label == "修改笔记"
    assert "folder_id" in args and args["folder_id"] is None


async def test_read_tool_runs_automatically_then_final_answer(monkeypatch):
    kb_id = uuid.uuid4()
    note_id = uuid.uuid4()
    client = _FakeClient(
        [
            _reply(
                thought="先搜一下",
                plan=["搜索相关笔记", "总结"],
                action={
                    "tool": "search_notes",
                    "args": {"query": "周报"},
                    "summary": "搜索周报笔记",
                    "step": 1,
                },
            ),
            _reply(
                thought="已有结果",
                action=None,
                answer="找到了一篇周报笔记。",
            ),
        ]
    )
    calls: list[tuple] = []

    async def fake_execute(session, kb_id_arg, tool, args):
        calls.append((session, kb_id_arg, tool, args))
        return {"total": 1, "items": [{"id": str(note_id), "title": "周报"}]}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)

    events = await _collect(_ctx(client, kb_id=kb_id), session=object())

    names = [name for name, _ in events]
    assert "plan" in names
    assert names.count("tool_call") == 1
    assert names.count("tool_result") == 1
    assert names[-1] == "done"
    assert events[-1][1]["ok"] is True
    assert [payload["text"] for name, payload in events if name == "chunk"] == [
        "找到了一篇周报笔记。"
    ]
    assert calls and calls[0][2] == "search_notes"
    # 第二轮请求已经带上工具结果。
    second_messages = client.completions.calls[1]["messages"]
    assert any("工具 search_notes 的执行结果" in item["content"] for item in second_messages)


async def test_fetch_url_runs_then_note_creation_waits_for_approval(monkeypatch):
    kb_id = uuid.uuid4()
    note_id = uuid.uuid4()
    page_body = "## 关雎\n\n关关雎鸠，在河之洲。"
    client = _FakeClient(
        [
            _reply(
                thought="先读取网页",
                plan=["读取网页", "新建笔记"],
                action={
                    "tool": "fetch_url",
                    "args": {"url": "https://www.guwendao.net/shiwenv_45.aspx"},
                    "summary": "读取古诗文网页",
                    "step": 1,
                },
            ),
            _reply(
                thought="已取得正文",
                plan=["读取网页", "新建笔记"],
                action={
                    "tool": "create_note",
                    "args": {"title": "关雎", "body_md": page_body},
                    "summary": "新建笔记《关雎》",
                    "step": 2,
                },
            ),
        ]
    )
    calls: list[str] = []

    async def fake_execute(session, kb_id_arg, tool, args):
        calls.append(tool)
        if tool == "fetch_url":
            return {"ok": True, "title": "关雎", "markdown": page_body}
        return {"ok": True, "note": {"id": str(note_id), "title": "关雎"}}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)

    events = await _collect(_ctx(client, kb_id=kb_id), session=object())
    names = [name for name, _ in events]
    # 网页读取自动执行后继续进入新建笔记，而不是停在「我先打开网页」。
    assert names.count("tool_call") == 2
    assert "approval" in names
    assert events[-1][0] == "done"
    assert events[-1][1]["awaiting_approval"] is True
    assert calls == ["fetch_url"]
    # 读取完成后要更新阶段文案，别让界面一直停在「正在分析并规划操作」。
    assert any(
        name == "stage"
        and payload.get("stage") == "agent"
        and "已读取网页" in payload.get("message", "")
        for name, payload in events
    )

    pending = agent_actions.claim(events[-1][1]["action_id"])
    assert pending is not None
    assert pending.tool == "create_note"
    assert pending.args["body_md"] == page_body


async def test_fast_path_uses_fetched_page_without_second_completion(monkeypatch):
    kb_id = uuid.uuid4()
    note_id = uuid.uuid4()
    client = _FakeClient(
        [
            _reply(
                thought="先读取网页",
                plan=["读取网页", "新建笔记"],
                action={
                    "tool": "fetch_url",
                    "args": {"url": "https://www.guwendao.net/shiwenv_45.aspx"},
                    "summary": "读取古诗文网页",
                    "step": 1,
                },
            )
        ]
    )
    executed: list[str] = []

    async def fake_execute(session, kb_id_arg, tool, args):
        executed.append(tool)
        if tool == "fetch_url":
            return {
                "ok": True,
                "title": "关雎",
                "markdown": "# 关雎\n\n关关雎鸠，在河之洲。",
                "final_url": "https://www.guwendao.net/shiwenv_45.aspx",
                "markdown_truncated": False,
            }
        return {"ok": True, "note": {"id": str(note_id), "title": "关雎"}}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    ctx = _ctx(client, kb_id=kb_id)
    ctx.user_query = (
        "将网页 https://www.guwendao.net/shiwenv_45.aspx 内容新建为笔记，"
        "放到知识库根目录下"
    )

    events = await _collect(ctx, session=object())
    names = [name for name, _ in events]
    assert "approval" in names
    # 快路径不再调用第二次模型来“重写”整页正文。
    assert len(client.completions.calls) == 1
    pending = agent_actions.claim(events[-1][1]["action_id"])
    assert pending is not None and pending.tool == "create_note"
    assert pending.args["title"] == "关雎"
    assert pending.args["body_md"].startswith("# 关雎")
    assert "来源：https://www.guwendao.net/shiwenv_45.aspx" in pending.args["body_md"]
    assert executed == ["fetch_url"]


def test_fast_path_eligibility_is_narrow():
    base = {
        "ok": True,
        "title": "关雎",
        "markdown": "# 关雎\n\n正文",
        "final_url": "https://example.com/a",
        "markdown_truncated": False,
    }
    plan = [{"id": "p1", "title": "读取网页"}, {"id": "p2", "title": "新建笔记"}]
    build = agent_fast_path.build_after_read_tool

    assert build("把网页内容新建为笔记，放到知识库根目录", "fetch_url", base, can_write=True, plan=plan)
    # 需要总结 / 指定分组 / 正文被截断时回退正常循环。
    assert build("总结网页内容并新建为笔记", "fetch_url", base, can_write=True, plan=plan) is None
    assert build("把网页内容新建为笔记，放到 生活/旅行 目录", "fetch_url", base, can_write=True, plan=plan) is None
    assert build("把网页内容新建为笔记", "fetch_url", {**base, "markdown_truncated": True}, can_write=True, plan=plan) is None
    # 多库 / 全局范围不能写入。
    assert build("把网页内容新建为笔记", "fetch_url", base, can_write=False, plan=plan) is None

    template = {
        "ok": True,
        "name": "旅游规划",
        "title_pattern": "{{date}} 旅游规划",
        "body_md": "# 旅游规划\n\n## 行程时间\n",
        "tags": ["旅行"],
        "body_truncated": False,
    }
    action = build("使用 旅游规划 模板新建一篇空白笔记", "get_template", template, can_write=True, plan=plan)
    assert action and action["args"]["title"].endswith("旅游规划")
    assert action["args"]["tags"] == ["旅行"]
    assert build("基于 旅游规划 模板，生成天津三日游内容", "get_template", template, can_write=True, plan=plan) is None


async def test_write_tool_waits_for_approval_then_resumes(monkeypatch):
    kb_id = uuid.uuid4()
    note_id = uuid.uuid4()
    client = _FakeClient(
        [
            _reply(
                thought="需要新建",
                plan=["新建笔记"],
                action={
                    "tool": "create_note",
                    "args": {"title": "新笔记", "body_md": "正文"},
                    "summary": "新建笔记《新笔记》",
                    "step": 1,
                },
            ),
        ]
    )
    executed: list[str] = []

    async def fake_execute(session, kb_id_arg, tool, args):
        executed.append(tool)
        return {"ok": True, "note": {"id": str(note_id), "title": "新笔记"}}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)

    events = await _collect(_ctx(client, kb_id=kb_id), session=object())
    names = [name for name, _ in events]
    assert "approval" in names
    assert names[-1] == "done"
    assert events[-1][1]["awaiting_approval"] is True
    assert executed == []

    action_id = events[-1][1]["action_id"]
    pending = agent_actions.claim(action_id)
    assert pending is not None
    assert pending.tool == "create_note"
    assert agent_actions.claim(action_id) is None

    # 模型偶尔会把 UUID 抄错：少 2 个字符时链接点击会 422。这里确认回答里的
    # 链接会被本轮真实笔记 id 修正。
    real_id = str(note_id)
    broken_id = real_id[:-6] + real_id[-4:]
    resume_client = _FakeClient(
        [
            _reply(
                thought="完成",
                action=None,
                answer=f"已创建 [新笔记](kiwi://note/{broken_id})。",
            )
        ]
    )
    ctx = _ctx(resume_client, kb_id=kb_id)
    ctx.messages = [dict(item) for item in pending.messages]
    resumed = await _collect(
        ctx, session=object(), resume=pending, approved=True
    )
    resumed_names = [name for name, _ in resumed]
    assert "tool_result" in resumed_names
    assert resumed[-1][0] == "done"
    assert resumed[-1][1]["ok"] is True
    assert resumed[-1][1].get("undo_id")
    assert [step["status"] for step in resumed[-1][1]["plan"]] == ["done"]
    assert executed == ["create_note"]
    assert (
        "stage",
        {"stage": "approve", "status": "done", "message": "已确认：新建笔记"},
    ) in resumed
    answer = "".join(
        payload["text"] for name, payload in resumed if name == "chunk"
    )
    assert f"kiwi://note/{real_id}" in answer
    assert broken_id not in answer


def test_repair_note_links_fuzzy_matches_when_title_differs():
    real_id = str(uuid.uuid4())
    broken_id = real_id[:-6] + real_id[-4:]
    answer = f"见 [旧标题](kiwi://note/{broken_id})。"
    fixed = agent_harness._repair_note_links(answer, {real_id: "新标题"})
    assert f"kiwi://note/{real_id}" in fixed
    assert broken_id not in fixed


def test_repair_note_links_keeps_valid_ids_and_unlinks_unfixable():
    known_id = str(uuid.uuid4())
    unknown_id = str(uuid.uuid4())
    keep = f"[已知](kiwi://note/{known_id}) [更早的笔记](kiwi://note/{unknown_id})"
    assert agent_harness._repair_note_links(keep, {known_id: "已知"}) == keep

    broken = "56c0256c-503b-4ca5-989c-8a4c1e4deb"
    unlinked = agent_harness._repair_note_links(
        f"见 [行宫](kiwi://note/{broken})。", {}
    )
    assert unlinked == "见 行宫。"


async def test_write_success_survives_model_disconnect(monkeypatch):
    import httpx
    from openai import APIConnectionError

    kb_id = uuid.uuid4()
    note_id = uuid.uuid4()

    class _BrokenCompletions:
        async def create(self, **kwargs):
            raise APIConnectionError(
                request=httpx.Request("POST", "http://test/v1/chat/completions")
            )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_BrokenCompletions())
    )
    executed: list[str] = []

    async def fake_execute(session, kb_id_arg, tool, args):
        executed.append(tool)
        return {"ok": True, "note": {"id": str(note_id), "title": "断连回执"}}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    monkeypatch.setattr(agent_harness, "MAX_LLM_RETRIES", 0)
    pending = agent_actions.PendingAction(
        tool="create_note",
        args={"title": "断连回执", "body_md": "正文"},
        summary="新建笔记《断连回执》",
        label="新建笔记",
        messages=[{"role": "system", "content": "资料"}],
        assistant_content="{}",
        plan=[],
        kb_id=str(kb_id),
        kb_ids=[str(kb_id)],
        scope_mode="kb",
        llm_config_id=None,
        model_override=None,
        intent="note",
    )

    events = await _collect(
        _ctx(client, kb_id=kb_id), session=object(), resume=pending, approved=True
    )
    chunks = "".join(
        payload.get("text", "") for name, payload in events if name == "chunk"
    )
    assert "已执行完成" in chunks
    assert f"kiwi://note/{note_id}" in chunks
    assert events[-1][0] == "done" and events[-1][1]["ok"] is True
    assert executed == ["create_note"]


async def test_rejected_action_never_executes(monkeypatch):
    pending = agent_actions.PendingAction(
        tool="delete_note",
        args={"note_id": str(uuid.uuid4())},
        summary="移入回收站",
        label="移入回收站",
        messages=[{"role": "system", "content": "资料"}, {"role": "user", "content": "删掉"}],
        assistant_content="{}",
        plan=[],
        kb_id=str(uuid.uuid4()),
        kb_ids=[],
        scope_mode="kb",
        llm_config_id=None,
        model_override=None,
        intent="note",
    )
    executed: list[str] = []

    async def fake_execute(*args, **kwargs):
        executed.append("called")
        return {"ok": True}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    events = await _collect(
        _ctx(_FakeClient([])), session=object(), resume=pending, approved=False
    )

    assert ("done", {"ok": True, "cancelled": True}) in events
    assert executed == []
    assert any("已取消" in payload.get("text", "") for _, payload in events)


async def test_write_tool_blocked_in_multi_scope_and_model_can_recover(monkeypatch):
    client = _FakeClient(
        [
            _reply(
                action={
                    "tool": "create_note",
                    "args": {"title": "不该写入"},
                    "summary": "新建",
                }
            ),
            _reply(action=None, answer="当前是多库范围，请切换到单个知识库后再编辑。"),
        ]
    )
    executed: list[str] = []

    async def fake_execute(*args, **kwargs):
        executed.append("called")
        return {"ok": True}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    events = await _collect(_ctx(client, scope_mode="multi"), session=object())

    names = [name for name, _ in events]
    assert "approval" not in names
    assert "notice" in names
    assert executed == []
    assert events[-1][0] == "done"


async def test_answer_with_system_prompt_leak_is_retried():
    leaked = (
        "## 备忘\n"
        "Agent 工具与行动协议\n"
        "权限：当前问题限定在单个知识库内，写工具可用，但必须先请求用户确认。\n"
        "当前日期：2026-11-21（星期六）\n"
    )
    clean = "LJ 笔记正文只有附件命名规范、SQL 排序规则和数据库连接信息。"
    client = _FakeClient(
        [
            _reply(action=None, answer=leaked),
            _reply(action=None, answer=clean),
        ]
    )

    events = await _collect(_ctx(client), session=object())

    assert [payload["text"] for name, payload in events if name == "chunk"] == [clean]
    assert any(name == "notice" for name, _ in events)
    assert events[-1][0] == "done"
    assert events[-1][1]["ok"] is True


def test_answer_echo_detection_ignores_normal_tool_mentions():
    prompt = "## Agent 工具与行动协议\n权限：当前问题限定在单个知识库内，写工具可用。"
    assert not agent_harness.answer_echoes_prompt(
        "我可以用 search_notes 搜索笔记，用 get_note 读全文。", prompt
    )
    assert agent_harness.answer_echoes_prompt(
        "Agent 工具与行动协议\n权限：当前问题限定在单个知识库内，写工具可用。",
        prompt,
    )


async def test_complete_retries_transient_connection_error(monkeypatch):
    import httpx
    from openai import APIConnectionError

    class _FlakyCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise APIConnectionError(
                    request=httpx.Request(
                        "POST", "http://test/v1/chat/completions"
                    )
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"answer":"ok"}')
                    )
                ]
            )

    completions = _FlakyCompletions()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(agent_harness.asyncio, "sleep", _no_sleep)
    text = await agent_harness._complete(_ctx(client))
    assert "ok" in text
    assert completions.calls == 2


def _dsml_call(tool: str, params: dict[str, tuple[str, str]]) -> str:
    lines = ["<｜｜DSML｜｜ calls>", f'<｜｜DSML｜｜ invoke name="{tool}">']
    for name, (string_flag, value) in params.items():
        lines.append(
            f'<｜｜DSML｜｜ parameter name="{name}" string="{string_flag}">{value}'
            "</｜｜DSML｜｜ parameter>"
        )
    lines += ["</｜｜DSML｜｜ invoke>", "</｜｜DSML｜｜ calls>"]
    return "\n".join(lines)


async def test_agent_trace_and_metrics_are_recorded(monkeypatch):
    from app.services import agent_trace
    from app.services.metrics import metrics

    agent_trace.clear()
    kb_id = uuid.uuid4()
    client = _FakeClient(
        [
            _reply(
                plan=["搜索周报", "总结"],
                action={
                    "tool": "search_notes",
                    "args": {"query": "周报"},
                    "summary": "搜索周报",
                    "step": 1,
                },
            ),
            _reply(action=None, answer="找到周报了。"),
        ]
    )

    async def fake_execute(session, kb_id_arg, tool, args):
        return {"total": 1, "items": [{"id": str(uuid.uuid4()), "title": "周报"}]}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    ctx = _ctx(client, kb_id=kb_id)
    ctx.user_query = "总结一下周报"
    ctx.planner_input = {"query": "周报"}
    ctx.planner_output = {"queries": ["周报"], "source": "rules"}
    ctx.planner_ms = 120
    events = await _collect(ctx, session=object())
    trace_ids = [
        payload.get("trace_id")
        for name, payload in events
        if name == "trace"
    ]
    assert trace_ids and trace_ids[0]

    traces = agent_trace.recent(1)
    assert traces, "应记录一轮 trace"
    trace = traces[0]
    assert trace["status"] == "done"
    assert trace["query"] == "总结一下周报"
    by_kind = {}
    for event in trace["events"]:
        by_kind.setdefault(event["kind"], event)
    assert {"planner", "model", "tool"} <= set(by_kind)
    assert by_kind["planner"]["input"]["query"] == "周报"
    assert by_kind["planner"]["output"]["queries"] == ["周报"]
    model_event = by_kind["model"]
    assert model_event["input"]["messages"]
    assert model_event["output"]
    assert model_event["meta"]["usage"]["total_tokens"] == 15
    assert model_event["meta"]["finish_reason"] == "stop"
    tool_event = by_kind["tool"]
    assert tool_event["input"]["tool"] == "search_notes"
    assert tool_event["output"]["items"]

    detail = agent_trace.get(trace_ids[0])
    assert detail is not None and detail["id"] == trace_ids[0]
    assert agent_trace.get("missing-trace") is None

    rendered = metrics.render()
    assert "kiwi_agent_turns_total" in rendered
    assert "kiwi_agent_model_seconds" in rendered
    assert "kiwi_agent_tool_seconds" in rendered


def test_unrecorded_trace_stays_out_of_ops_list():
    from app.services import agent_trace

    agent_trace.clear()
    trace = agent_trace.start_trace(
        query="你好", model="m", scope="kb", record=False
    )
    trace.event("understand", "理解范围")
    assert trace.events
    assert agent_trace.get(trace.id) is None
    assert agent_trace.recent(10) == []


def test_native_tool_markup_is_converted_to_action():
    dsml = _dsml_call(
        "create_note",
        {
            "title": ("true", "测试标题"),
            "tags": ("false", '["a", "b"]'),
            "body_md": ("true", "# 正文\n\n没有 JSON"),
        },
    )
    reply = agent_harness._parse_reply_with_dsml(dsml)
    assert reply.action is not None
    assert reply.action["tool"] == "create_note"
    assert reply.action["args"]["title"] == "测试标题"
    assert reply.action["args"]["tags"] == ["a", "b"]
    assert reply.action["args"]["body_md"].startswith("# 正文")
    # 写回历史的内容必须是协议 JSON，不能留下原生标记。
    assert "DSML" not in reply.raw
    assert json.loads(reply.raw)["action"]["tool"] == "create_note"


async def test_native_tool_markup_runs_tool_and_keeps_history_clean(monkeypatch):
    kb_id = uuid.uuid4()
    note_id = uuid.uuid4()
    dsml = _dsml_call(
        "create_note",
        {
            "title": ("true", "行宫"),
            "body_md": ("true", "# 行宫\n\n正文"),
        },
    )
    client = _FakeClient([dsml])
    executed: list[str] = []

    async def fake_execute(session, kb_id_arg, tool, args):
        executed.append(tool)
        return {"ok": True, "note": {"id": str(note_id), "title": "行宫"}}

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)

    events = await _collect(_ctx(client, kb_id=kb_id), session=object())
    names = [name for name, _ in events]
    assert "approval" in names
    assert events[-1][1]["awaiting_approval"] is True
    assert not any(
        "DSML" in str(payload.get("text", "")) for _, payload in events
    )

    pending = agent_actions.claim(events[-1][1]["action_id"])
    assert pending is not None and pending.tool == "create_note"
    assert pending.args["title"] == "行宫"
    assert "DSML" not in pending.assistant_content
    assert executed == []


async def test_unparseable_native_markup_is_retried_then_answered():
    bad = "<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name=\"\">\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>"
    client = _FakeClient([bad, _reply(action=None, answer="已经改好了")])

    events = await _collect(_ctx(client), session=object())
    names = [name for name, _ in events]
    assert "notice" in names
    assert [payload["text"] for name, payload in events if name == "chunk"] == [
        "已经改好了"
    ]
    assert events[-1][0] == "done" and events[-1][1]["ok"] is True


async def test_unparseable_native_markup_stops_with_readable_error():
    bad = "<｜｜DSML｜｜ calls>\n</｜｜DSML｜｜ calls>"
    client = _FakeClient([bad, bad, bad])

    events = await _collect(_ctx(client), session=object())
    chunks = [payload["text"] for name, payload in events if name == "chunk"]
    assert chunks and all("DSML" not in text for text in chunks)
    assert events[-1] == (
        "done",
        {"ok": False, "plan": []},
    )


def test_system_prompt_includes_current_week_range():
    now = datetime.now(app_timezone())
    monday = now - timedelta(days=now.weekday())
    prompt = agent_harness.agent_system_prompt(
        can_write=False,
        toolbox=Toolbox(agent_tools.builtin_tools()),
        max_steps=6,
    )

    assert monday.strftime("%Y-%m-%d") in prompt
    assert (monday + timedelta(days=6)).strftime("%Y-%m-%d") in prompt
    assert "$week_start" not in prompt
    assert "$week_end" not in prompt
