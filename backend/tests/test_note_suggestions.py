"""笔记整理建议：标签推荐、关联标记与近似重复检测。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException


async def _create_tag(client, kb_id: str, name: str) -> dict:
    resp = await client.post(f"/api/notes/tags?kb_id={kb_id}", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_parse_tag_array_tolerates_fences_and_duplicates():
    from app.routers.notes_suggestions import parse_tag_array

    assert parse_tag_array('```json\n["前端", "前端", "#缓存"]\n```') == ["前端", "缓存"]
    assert parse_tag_array("这里没有数组") == []
    assert parse_tag_array('[{"name": "对象不是标签"}]') == []


async def test_tag_suggestions_match_existing_vocabulary(client, kb, note_factory):
    await _create_tag(client, kb["id"], "性能优化")
    await _create_tag(client, kb["id"], "前端/渲染")
    note = await note_factory(
        title="页面性能优化记录",
        body_md="本次主要处理前端渲染耗时，性能优化后首屏更快。",
    )

    resp = await client.get(f"/api/notes/{note['id']}/tag-suggestions?kb_id={kb['id']}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    names = [item["name"] for item in data["tags"]]
    assert "性能优化" in names
    assert "前端/渲染" in names
    assert all(item["source"] == "existing" for item in data["tags"])
    assert data["ai_error"] is None

    # 已挂到笔记上的标签不再重复推荐。
    await client.put(
        f"/api/notes/{note['id']}/tags?kb_id={kb['id']}",
        json={"names": ["性能优化"]},
    )
    resp = await client.get(f"/api/notes/{note['id']}/tag-suggestions?kb_id={kb['id']}")
    names = [item["name"] for item in resp.json()["tags"]]
    assert "性能优化" not in names


async def test_ai_tag_suggestions_use_llm_output(client, kb, note_factory, monkeypatch):
    from app.routers import notes_suggestions

    note = await note_factory(title="复盘", body_md="记录一次性能优化与缓存设计的复盘。")

    async def fake_resolve(session, kb_id, temp_cfg_id):
        return SimpleNamespace(base_url="http://mock", model_name="mock-model"), "key"

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='```json\n["性能优化","缓存","性能优化"]\n```'
                        )
                    )
                ]
            )

    class FakeClient:
        chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(notes_suggestions, "resolve_llm", fake_resolve)
    monkeypatch.setattr(
        notes_suggestions.llm_factory, "get_client", lambda *args, **kwargs: FakeClient()
    )

    resp = await client.get(
        f"/api/notes/{note['id']}/tag-suggestions?kb_id={kb['id']}&ai=1"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ai_tags = [item["name"] for item in data["tags"] if item["source"] == "ai"]
    assert ai_tags == ["性能优化", "缓存"]
    assert data["ai_error"] is None


async def test_ai_tag_suggestions_without_llm_reports_error(
    client, kb, note_factory, monkeypatch
):
    from app.routers import notes_suggestions

    note = await note_factory(title="无模型", body_md="一段普通正文。")

    async def no_llm(session, kb_id, temp_cfg_id):
        raise HTTPException(400, "未配置大模型连接，请先在设置中添加并设为默认。")

    monkeypatch.setattr(notes_suggestions, "resolve_llm", no_llm)

    resp = await client.get(
        f"/api/notes/{note['id']}/tag-suggestions?kb_id={kb['id']}&ai=1"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ai_error"] == "未配置大模型连接，请先在设置中添加并设为默认。"


async def test_related_marks_duplicates_and_existing_links(client, kb, note_factory):
    body = (
        "缓存设计需要关注命中率、失效策略与一致性，"
        "本文记录一次完整的缓存改造复盘，包括压测数据与回滚方案。"
    ) * 3
    source = await note_factory(title="缓存改造复盘", body_md=body)
    duplicate = await note_factory(title="缓存改造复盘副本", body_md=f"{body}\n\n补充一句话。")
    linked = await note_factory(title="缓存术语表", body_md="命中率、失效策略与一致性。")

    await client.patch(
        f"/api/notes/{source['id']}?kb_id={kb['id']}",
        json={"body_md": f"{body}\n\n参考 [[缓存术语表]]。"},
    )

    resp = await client.get(f"/api/notes/related/{source['id']}?kb_id={kb['id']}")
    assert resp.status_code == 200, resp.text
    items = {item["note"]["id"]: item for item in resp.json()}

    assert items[duplicate["id"]]["duplicate"] is True
    assert items[duplicate["id"]]["linked"] is False
    assert items[duplicate["id"]]["similarity"] > 0.5

    assert items[linked["id"]]["linked"] is True
    assert items[linked["id"]]["duplicate"] is False
    assert any("双向链接" in reason for reason in items[linked["id"]]["reasons"])
