"""编辑器内置扩展组件：清单、启停持久化与未知 key 校验。"""

from __future__ import annotations

EXPECTED_KEYS = [
    "date",
    "formula",
    "mermaid",
    "gallery",
    "columns2",
    "columns3",
    "calendar",
    "datatable",
    "taskProgress",
]


async def test_editor_extension_catalog(client):
    resp = await client.get("/api/editor/extensions")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [item["key"] for item in data["items"]] == EXPECTED_KEYS
    assert data["items"][0]["label"] == "日期"
    assert data["items"][0]["icon"] == "calendar"
    assert all(item["group"] == "扩展组件" for item in data["items"])
    # 设置页预览样例：每个内置组件都要有可渲染的 Markdown。
    assert all(item["preview_markdown"].strip() for item in data["items"])
    assert "📅" in data["items"][0]["preview_markdown"]
    samples = {item["key"]: item["preview_markdown"] for item in data["items"]}
    # 分栏样例必须为每栏保留独立的块，否则阅读视图会把标记当作正文。
    assert samples["columns2"].count("[!COLUMN]") == 2
    assert samples["columns3"].count("[!COLUMN]") == 3
    assert samples["mermaid"].startswith("```mermaid")


async def test_editor_extension_toggle_persists(client):
    # 先恢复默认，避免其他测试或手工操作留下的状态影响断言。
    reset = await client.put("/api/editor/extensions", json={"disabled": []})
    assert reset.status_code == 200

    saved = await client.put(
        "/api/editor/extensions",
        json={"disabled": ["mermaid", "columns3", "mermaid"]},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    # 去重并保持注册表顺序。
    assert body["disabled"] == ["mermaid", "columns3"]
    assert "mermaid" not in body["enabled"]
    assert "columns3" not in body["enabled"]
    state = {item["key"]: item["enabled"] for item in body["items"]}
    assert state["mermaid"] is False
    assert state["columns3"] is False
    assert state["date"] is True

    reloaded = await client.get("/api/editor/extensions")
    assert reloaded.json()["disabled"] == ["mermaid", "columns3"]

    # 未知 key 拒绝，且不破坏已保存状态。
    unknown = await client.put(
        "/api/editor/extensions", json={"disabled": ["not-a-component"]}
    )
    assert unknown.status_code == 400
    assert "not-a-component" in unknown.json()["detail"]
    assert (await client.get("/api/editor/extensions")).json()["disabled"] == [
        "mermaid",
        "columns3",
    ]

    restored = await client.put("/api/editor/extensions", json={"disabled": []})
    assert restored.status_code == 200
    assert restored.json()["disabled"] == []
    assert len(restored.json()["enabled"]) == len(EXPECTED_KEYS)
