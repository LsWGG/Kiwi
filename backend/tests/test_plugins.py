"""组件插件：列表、元信息、导入冲突、校验与开发规范。

详细的 zip 导入 / 资源下发 / 导出往返见 test_plugin_components.py。
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest

SCRIPT = """export function setup(host) {
  const { h } = host.vue
  const Agenda = {
    props: ['blockProps'],
    setup(props) {
      return () => h('div', String(props.blockProps.title || '议程'))
    },
  }
  return { blocks: { agenda: { component: Agenda } } }
}
"""


def component_manifest(key: str, **overrides):
    data = {
        "manifest_version": 1,
        "kind": "component",
        "key": key,
        "name": "会议工具",
        "version": "1.0.0",
        "description": "会议议程组件",
        "author": "Kiwi",
        "icon": "puzzle",
        "entry": "index.js",
        "blocks": [
            {
                "type": "agenda",
                "label": "会议议程",
                "icon": "list",
                "description": "插入会议议程",
                "category": "会议",
                "default_props": {"title": "议程"},
            }
        ],
        "settings": [],
    }
    data.update(overrides)
    return data


def make_zip(
    manifest: dict,
    *,
    directory: str = "meeting",
    script: str | None = SCRIPT,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        prefix = f"{directory}/" if directory else ""
        archive.writestr(f"{prefix}plugin.json", json.dumps(manifest))
        if script is not None:
            archive.writestr(f"{prefix}{manifest.get('entry') or 'index.js'}", script)
    return buffer.getvalue()


@pytest.fixture
async def plugin(client):
    key = f"pytest-plugin-{uuid.uuid4().hex[:8]}"
    package = make_zip(component_manifest(key))
    resp = await client.post(
        "/api/plugins/import",
        files={"file": ("meeting.zip", package, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/plugins/{data['id']}")


async def test_plugin_list_metadata_and_toggle(client, plugin):
    listed = await client.get("/api/plugins")
    assert listed.status_code == 200
    row = next(item for item in listed.json() if item["id"] == plugin["id"])
    assert row["kind"] == "component"
    assert row["entry"] == "index.js"

    blocks = await client.get("/api/plugins/blocks")
    assert blocks.status_code == 200
    block = next(
        item for item in blocks.json() if item["plugin_key"] == plugin["key"]
    )
    assert block["key"] == f"{plugin['key']}:agenda"
    assert block["kind"] == "component"
    assert block["default_props"] == {"title": "议程"}
    assert block["template_markdown"] == ""

    disabled = await client.patch(
        f"/api/plugins/{plugin['id']}", json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    blocks = await client.get("/api/plugins/blocks")
    assert plugin["key"] not in {item["plugin_key"] for item in blocks.json()}

    updated = await client.patch(
        f"/api/plugins/{plugin['id']}",
        json={"name": "会议工具（改）", "version": "1.1.0", "enabled": True},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "会议工具（改）"
    assert body["version"] == "1.1.0"
    assert body["enabled"] is True
    # 元信息更新不影响入口脚本。
    assert body["script_size"] == len(SCRIPT)

    deleted = await client.delete(f"/api/plugins/{plugin['id']}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/plugins/{plugin['id']}")
    assert missing.status_code == 404


async def test_plugin_import_conflicts_and_overwrite(client):
    key = f"imported-{uuid.uuid4().hex[:8]}"
    manifest = component_manifest(key)
    package = make_zip(manifest)
    created = await client.post(
        "/api/plugins/import",
        files={"file": ("meeting.zip", package, "application/zip")},
    )
    assert created.status_code == 201, created.text
    plugin_id = created.json()["id"]
    try:
        assert created.json()["source"] == "import"

        # 同 key 默认拒绝，overwrite=true 原地更新。
        conflict = await client.post(
            "/api/plugins/import",
            files={"file": ("meeting.zip", package, "application/zip")},
        )
        assert conflict.status_code == 409

        updated = make_zip(component_manifest(key, version="1.1.0"))
        overwritten = await client.post(
            "/api/plugins/import?overwrite=true",
            files={"file": ("meeting.zip", updated, "application/zip")},
        )
        assert overwritten.status_code == 201, overwritten.text
        assert overwritten.json()["id"] == plugin_id
        assert overwritten.json()["version"] == "1.1.0"
    finally:
        await client.delete(f"/api/plugins/{plugin_id}")


async def test_plugin_validation_errors(client):
    key = f"invalid-{uuid.uuid4().hex[:8]}"

    # 模板插件已不再支持。
    template = make_zip(component_manifest(key, kind="template"))
    rejected_kind = await client.post(
        "/api/plugins/import",
        files={"file": ("meeting.zip", template, "application/zip")},
    )
    assert rejected_kind.status_code == 400
    assert "组件插件" in rejected_kind.json()["detail"]

    # 非 zip 直接拒绝。
    raw = json.dumps(component_manifest(key)).encode()
    not_zip = await client.post(
        "/api/plugins/import",
        files={"file": ("plugin.json", raw, "application/json")},
    )
    assert not_zip.status_code == 400
    assert "zip" in not_zip.json()["detail"].lower()

    # zip 内 manifest 不是合法 JSON。
    broken_buffer = io.BytesIO()
    with zipfile.ZipFile(broken_buffer, "w") as archive:
        archive.writestr("broken/plugin.json", "{not json")
    broken = await client.post(
        "/api/plugins/import",
        files={
            "file": ("broken.zip", broken_buffer.getvalue(), "application/zip")
        },
    )
    assert broken.status_code == 400

    # 缺少 manifest。
    empty_buffer = io.BytesIO()
    with zipfile.ZipFile(empty_buffer, "w") as archive:
        archive.writestr("readme.md", "# empty")
    missing = await client.post(
        "/api/plugins/import",
        files={
            "file": ("bundle.zip", empty_buffer.getvalue(), "application/zip")
        },
    )
    assert missing.status_code == 400

    # 重复区块 type。
    duplicate = make_zip(
        component_manifest(
            key,
            blocks=[
                {"type": "same", "label": "一"},
                {"type": "same", "label": "二"},
            ],
        )
    )
    duplicate_resp = await client.post(
        "/api/plugins/import",
        files={"file": ("dupe.zip", duplicate, "application/zip")},
    )
    assert duplicate_resp.status_code == 400
    assert "重复" in duplicate_resp.json()["detail"]

    # 非法 key。
    bad_key = make_zip(component_manifest("Bad Key!"))
    bad_key_resp = await client.post(
        "/api/plugins/import",
        files={"file": ("bad.zip", bad_key, "application/zip")},
    )
    assert bad_key_resp.status_code == 400


async def test_legacy_template_plugin_hidden_from_lists(client, db):
    """历史模板记录保留可读，但不进入插件列表与编辑器区块清单。"""
    from app.db.models import Plugin

    key = f"legacy-{uuid.uuid4().hex[:8]}"
    row = Plugin(
        key=key,
        name="历史模板插件",
        kind="template",
        enabled=True,
        source="manual",
        manifest={
            "kind": "template",
            "blocks": [
                {
                    "type": "agenda",
                    "label": "会议议程",
                    "template_markdown": "## 议程\n",
                }
            ],
        },
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    try:
        listed = await client.get("/api/plugins")
        assert listed.status_code == 200
        assert key not in {item["key"] for item in listed.json()}

        blocks = await client.get("/api/plugins/blocks")
        assert blocks.status_code == 200
        assert key not in {item["plugin_key"] for item in blocks.json()}

        # 历史记录仍可按 id 读取，不做破坏性迁移。
        detail = await client.get(f"/api/plugins/{row.id}")
        assert detail.status_code == 200
    finally:
        await db.delete(row)
        await db.commit()


async def test_plugin_spec_is_component_only(client):
    spec = await client.get("/api/plugins/spec")
    assert spec.status_code == 200
    body = spec.json()
    assert body["kind"] == "component"
    assert body["manifest_version"] == 1
    assert set(body["examples"]) == {"component"}
    assert body["example"]["kind"] == "component"
    assert body["example"]["blocks"]
    assert body["example"]["entry"] == "index.js"
    assert "host.theme" in body["fields"]
    assert any("主题色" in rule for rule in body["rules"])
    assert body["skill"] == "kiwi-plugin"
