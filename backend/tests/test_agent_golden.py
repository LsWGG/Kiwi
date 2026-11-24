"""Agent 固定场景评测（golden set）。

与单点工具测试不同，这里按「一轮真实任务的工具序列与审批」断言，防止改动
提示词 / 快路径 / 工具注册后把常见任务退回多轮试错。模型响应是脚本化的，
CI 不依赖真实模型。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.services import agent_actions, agent_harness, agent_tools


class _ScriptedCompletions:
    def __init__(self, replies: list[str]):
        self.replies = iter(replies)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=next(self.replies))
                )
            ]
        )


def _client(replies: list[str]):
    completions = _ScriptedCompletions(replies)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    ), completions


def _reply(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _ctx(client, *, user_query: str = ""):
    kb_id = uuid.uuid4()
    return agent_harness.AgentContext(
        messages=[{"role": "system", "content": "资料"}],
        citations=[],
        intent="note",
        client=client,
        model_name="golden-model",
        temperature=0,
        kb_id=kb_id,
        kb_ids=[kb_id],
        llm_config_id=None,
        model_override=None,
        scope_mode="kb",
        user_query=user_query,
    )


async def _run(ctx, session=None):
    return [
        event
        async for event in agent_harness.run_agent(ctx, session or object())
    ]


@pytest.fixture(autouse=True)
def _clear_actions():
    agent_actions.clear()
    yield
    agent_actions.clear()


async def test_golden_url_to_note_uses_one_model_call(monkeypatch):
    """URL → 笔记：读完网页后直接给出待确认动作，不再让模型重写正文。"""
    client, completions = _client(
        [
            _reply(
                thought="读取网页",
                plan=["读取网页", "新建笔记"],
                action={
                    "tool": "fetch_url",
                    "args": {"url": "https://example.com/poem"},
                    "summary": "读取网页",
                    "step": 1,
                },
            )
        ]
    )

    async def fake_execute(session, kb_id, tool, args):
        assert tool == "fetch_url"
        return {
            "ok": True,
            "title": "关雎",
            "markdown": "# 关雎\n\n关关雎鸠。",
            "final_url": "https://example.com/poem",
            "markdown_truncated": False,
        }

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    events = await _run(
        _ctx(
            client,
            user_query="把网页 https://example.com/poem 新建为笔记，放到知识库根目录",
        )
    )

    names = [name for name, _ in events]
    assert names[-1] == "done"
    assert events[-1][1]["awaiting_approval"] is True
    assert len(completions.calls) == 1
    pending = agent_actions.claim(events[-1][1]["action_id"])
    assert pending is not None
    assert pending.tool == "create_note"
    assert pending.args["title"] == "关雎"
    assert "来源：https://example.com/poem" in pending.args["body_md"]


async def test_golden_template_to_note_tool_sequence(monkeypatch):
    """「基于模板生成」：先查模板库、读正文，再提出新建笔记，不搜索笔记猜模板。"""
    client, completions = _client(
        [
            _reply(
                thought="查找模板",
                plan=["查找模板", "读取正文", "新建笔记"],
                action={
                    "tool": "list_templates",
                    "args": {"query": "旅游规划"},
                    "summary": "查找旅游规划模板",
                    "step": 1,
                },
            ),
            _reply(
                thought="读取模板",
                plan=["查找模板", "读取正文", "新建笔记"],
                action={
                    "tool": "get_template",
                    "args": {"name": "旅游规划"},
                    "summary": "读取模板正文",
                    "step": 2,
                },
            ),
            _reply(
                thought="生成笔记",
                plan=["查找模板", "读取正文", "新建笔记"],
                action={
                    "tool": "create_note",
                    "args": {
                        "title": "北京出发·天津三日游",
                        "body_md": "# 旅游规划\n\n出行信息待确认。",
                    },
                    "summary": "新建天津三日游笔记",
                    "step": 3,
                },
            ),
        ]
    )
    tools: list[str] = []

    async def fake_execute(session, kb_id, tool, args):
        tools.append(tool)
        if tool == "list_templates":
            return {
                "items": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "旅游规划",
                        "body_preview": "# 旅游规划",
                    }
                ]
            }
        if tool == "get_template":
            return {
                "id": str(uuid.uuid4()),
                "name": "旅游规划",
                "title_pattern": "旅游规划",
                "body_md": "# 旅游规划\n\n## 行程时间\n",
                "tags": ["旅行"],
                "body_truncated": False,
            }
        raise AssertionError(f"不应执行写工具：{tool}")

    monkeypatch.setattr(agent_tools, "execute_tool", fake_execute)
    events = await _run(
        _ctx(
            client,
            user_query="基于 旅游规划 模板，生成北京出发天津三日游笔记，放到知识库根目录",
        )
    )

    assert tools == ["list_templates", "get_template"]
    assert len(completions.calls) == 3
    assert events[-1][1]["awaiting_approval"] is True
    pending = agent_actions.claim(events[-1][1]["action_id"])
    assert pending is not None and pending.tool == "create_note"
    assert "天津" in pending.args["title"]
    # 模型没有先搜索笔记去找模板。
    called = [
        payload["tool"] for name, payload in events if name == "tool_call"
    ]
    assert called == ["list_templates", "get_template", "create_note"]
    assert "search_notes" not in called
