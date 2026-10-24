"""组件插件：预检、zip 导入、资源下发、导出与内置包导出。"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest

SCRIPT = """export function setup(host) {
  const { h } = host.vue
  const Counter = {
    props: ['blockProps', 'readonly', 'selected', 'updateProps'],
    setup(props) {
      return () => h('button', { class: 'counter' }, String(props.blockProps.count || 0))
    },
  }
  return { blocks: { counter: { component: Counter } } }
}
"""

STYLE = ".counter { color: #0f766e; }\n"


def component_manifest(key: str, **overrides):
    data = {
        "manifest_version": 1,
        "kind": "component",
        "key": key,
        "name": "测试计数器",
        "version": "1.2.3",
        "description": "用于组件插件测试",
        "author": "pytest",
        "icon": "checkSquare",
        "entry": "index.js",
        "style": "style.css",
        "blocks": [
            {
                "type": "counter",
                "label": "计数器",
                "icon": "checkSquare",
                "description": "可增减的计数卡片",
                "category": "测试",
                "default_props": {"label": "计数", "count": 2},
            }
        ],
        "settings": [],
    }
    data.update(overrides)
    return data


def make_zip(
    manifest: dict,
    *,
    directory: str = "counter",
    script: str | None = SCRIPT,
    style: str | None = STYLE,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        prefix = f"{directory}/" if directory else ""
        archive.writestr(f"{prefix}plugin.json", json.dumps(manifest))
        if script is not None:
            entry = str(manifest.get("entry") or "index.js")
            archive.writestr(f"{prefix}{entry}", script)
        if style is not None:
            style_path = str(manifest.get("style") or "style.css")
            archive.writestr(f"{prefix}{style_path}", style)
    return buffer.getvalue()


@pytest.fixture
def plugin_key():
    return f"pytest-component-{uuid.uuid4().hex[:8]}"


async def test_component_plugin_inspect_import_serve_and_export(client, plugin_key):
    manifest = component_manifest(plugin_key)
    package = make_zip(manifest)

    inspected = await client.post(
        "/api/plugins/inspect",
        files={"file": ("counter.zip", package, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json() == {
        "kind": "component",
        "key": plugin_key,
        "name": "测试计数器",
        "version": "1.2.3",
        "description": "用于组件插件测试",
        "entry": "index.js",
        "style": "style.css",
        "has_script": True,
        "has_style": True,
        "block_count": 1,
        "blocks": ["计数器"],
    }

    imported = await client.post(
        "/api/plugins/import",
        files={"file": ("counter.zip", package, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    plugin = imported.json()
    try:
        assert plugin["kind"] == "component"
        assert plugin["has_script"] is True
        assert plugin["has_style"] is True
        assert plugin["entry"] == "index.js"
        assert plugin["script_size"] == len(SCRIPT)
        assert plugin["script_url"].startswith(f"/api/plugins/{plugin['id']}/bundle.js?v=")
        assert plugin["blocks"][0]["kind"] == "component"
        assert plugin["blocks"][0]["default_props"] == {"label": "计数", "count": 2}
        assert plugin["blocks"][0]["template_markdown"] == ""

        bundle = await client.get(f"/api/plugins/{plugin['id']}/bundle.js")
        assert bundle.status_code == 200
        assert bundle.text == SCRIPT
        assert bundle.headers["content-type"].startswith("text/javascript")
        assert bundle.headers["x-content-type-options"] == "nosniff"

        style = await client.get(f"/api/plugins/{plugin['id']}/style.css")
        assert style.status_code == 200
        assert style.text == STYLE
        assert style.headers["content-type"].startswith("text/css")

        blocks = await client.get("/api/plugins/blocks")
        row = next(item for item in blocks.json() if item["plugin_key"] == plugin_key)
        assert row["kind"] == "component"

        # 停用只影响编辑器清单；显式预览仍可读取已安装的脚本。
        disabled = await client.patch(
            f"/api/plugins/{plugin['id']}", json={"enabled": False}
        )
        assert disabled.status_code == 200
        blocks = await client.get("/api/plugins/blocks")
        assert plugin_key not in {item["plugin_key"] for item in blocks.json()}
        assert (await client.get(f"/api/plugins/{plugin['id']}/bundle.js")).status_code == 200

        exported = await client.get(f"/api/plugins/{plugin['id']}/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            names = set(archive.namelist())
            assert {"plugin.json", "README.md", "index.js", "style.css"} <= names
            exported_manifest = json.loads(archive.read("plugin.json"))
            assert exported_manifest["kind"] == "component"
            assert exported_manifest["key"] == plugin_key
            assert archive.read("index.js").decode() == SCRIPT

        # 导出的包可以被覆盖导入，保证往返可用。
        roundtrip = await client.post(
            "/api/plugins/import?overwrite=true",
            files={"file": ("counter.zip", exported.content, "application/zip")},
        )
        assert roundtrip.status_code == 201, roundtrip.text
        assert roundtrip.json()["id"] == plugin["id"]
        assert roundtrip.json()["script_size"] == len(SCRIPT)
    finally:
        await client.delete(f"/api/plugins/{plugin['id']}")


async def test_component_plugin_requires_zip_and_safe_paths(client, plugin_key):
    raw = json.dumps(component_manifest(plugin_key)).encode()
    rejected = await client.post(
        "/api/plugins/import",
        files={"file": ("plugin.json", raw, "application/json")},
    )
    assert rejected.status_code == 400
    assert "zip" in rejected.json()["detail"].lower()

    traversal = component_manifest(plugin_key, entry="../evil.js")
    bad = await client.post(
        "/api/plugins/import",
        files={"file": ("bad.zip", make_zip(traversal), "application/zip")},
    )
    assert bad.status_code == 400
    assert "上级目录" in bad.json()["detail"]

    missing = component_manifest(plugin_key)
    absent = await client.post(
        "/api/plugins/import",
        files={
            "file": (
                "missing.zip",
                make_zip(missing, script=None),
                "application/zip",
            )
        },
    )
    assert absent.status_code == 400 or absent.status_code == 404


async def test_component_plugin_create_endpoint_removed(client, plugin_key):
    """组件插件只能通过 zip 导入；旧的 JSON 创建入口已移除。"""
    resp = await client.post("/api/plugins", json=component_manifest(plugin_key))
    assert resp.status_code == 405


async def test_dev_kit_and_builtin_exports(client):
    single = await client.get("/api/editor/extensions/gallery/export")
    assert single.status_code == 200
    assert single.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(single.content)) as archive:
        names = set(archive.namelist())
        assert {"plugin.json", "preview.json", "README.md"} <= names
        manifest = json.loads(archive.read("plugin.json"))
        assert manifest["kind"] == "builtin"
        assert manifest["builtin"] == "gallery"
        assert manifest["blocks"][0]["node"] == "kiwiGallery"
        assert "source/gallery.ts" in names

    all_builtins = await client.get("/api/editor/extensions/export")
    assert all_builtins.status_code == 200
    with zipfile.ZipFile(io.BytesIO(all_builtins.content)) as archive:
        manifests = [
            name
            for name in archive.namelist()
            if name.endswith("/plugin.json")
        ]
        assert len(manifests) == 9

    missing = await client.get("/api/editor/extensions/not-a-real-extension/export")
    assert missing.status_code == 404

    dev_kit = await client.get("/api/plugins/dev-kit")
    assert dev_kit.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dev_kit.content)) as archive:
        names = set(archive.namelist())
        assert "kiwi-plugin-dev-kit/docs/PLUGIN_SPEC.md" in names
        assert "kiwi-plugin-dev-kit/docs/examples/plugins/README.md" in names
        assert "kiwi-plugin-dev-kit/docs/examples/plugins/counter/index.js" in names
        assert "kiwi-plugin-dev-kit/docs/examples/plugins/pomodoro/index.js" in names
        assert "kiwi-plugin-dev-kit/docs/examples/plugins/countdown/style.css" in names
        assert "kiwi-plugin-dev-kit/.claude/skills/kiwi-plugin/SKILL.md" in names
        prompt = archive.read("kiwi-plugin-dev-kit/AI_PROMPT.md").decode("utf-8")
        assert "pomodoro" in prompt and "countdown" in prompt
