"""主题插件：内置主题、应用 / 覆盖值、导入导出与开发套件。"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest

DEFAULT_KEY = "kiwi-classic"


def theme_manifest(key: str, **overrides) -> dict:
    data = {
        "manifest_version": 1,
        "kind": "theme",
        "key": key,
        "name": "极光测试",
        "version": "1.0.0",
        "description": "仅用于 pytest 的深色主题",
        "author": "Kiwi",
        "icon": "palette",
        "homepage": "",
        "entry": "",
        "style": "theme.css",
        "blocks": [],
        "theme": {
            "mode": "dark",
            "colors": {
                "app.background": "#0b1020",
                "surface.background": "#121a30",
                "surface.muted": "#1a2540",
                "surface.strong": "#253356",
                "border.subtle": "#1c2742",
                "border.default": "#2a3a5e",
                "border.strong": "#3b4f7a",
                "text.primary": "#e7ecff",
                "text.strong": "#d3ddfc",
                "text.secondary": "#b1bfe8",
                "text.muted": "#8b9bc4",
                "text.subtle": "#6f7fa8",
                "text.faint": "#56668c",
                "accent": "#5eead4",
                "accent.foreground": "#062a25",
            },
            "background": {
                "image": "assets/bg.svg",
                "size": "cover",
                "position": "center",
                "repeat": "no-repeat",
                "dim": 0.2,
                "blur": 1,
            },
            "surface": {"opacity": 0.8, "blur": 10},
            "typography": {"body": "", "heading": "", "mono": ""},
            "preview": "assets/preview.svg",
        },
    }
    data.update(overrides)
    return data


def make_theme_zip(manifest: dict, *, directory: str = "aurora") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        prefix = f"{directory}/" if directory else ""
        archive.writestr(f"{prefix}plugin.json", json.dumps(manifest))
        archive.writestr(
            f"{prefix}theme.css",
            f'html[data-kiwi-theme="{manifest["key"]}"] .glass {{ border-color: #2a3a5e; }}\n',
        )
        archive.writestr(
            f"{prefix}assets/bg.svg",
            '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#0b1020"/></svg>',
        )
        archive.writestr(
            f"{prefix}assets/preview.svg",
            '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="5"><rect width="8" height="5" fill="#121a30"/></svg>',
        )
    return buffer.getvalue()


@pytest.fixture(autouse=True)
async def reset_theme(client):
    """每个用例结束后恢复默认主题，避免影响其他测试。"""
    yield
    await client.put("/api/themes/active", json={"key": DEFAULT_KEY, "overrides": {}})


@pytest.fixture
async def theme_plugin(client):
    key = f"pytest-theme-{uuid.uuid4().hex[:8]}"
    package = make_theme_zip(theme_manifest(key))
    resp = await client.post(
        "/api/themes/import",
        files={"file": ("aurora.zip", package, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/plugins/{data['id']}")


async def test_builtin_theme_list_and_export(client):
    resp = await client.get("/api/themes")
    assert resp.status_code == 200
    rows = resp.json()
    classic = next(item for item in rows if item["key"] == DEFAULT_KEY)
    assert classic["builtin"] is True
    assert classic["enabled"] is True
    assert classic["theme"]["mode"] == "light"
    # 内置主题不声明 accent，由主题引擎回落到内置默认色。
    assert "accent" not in classic["theme"]["colors"]

    exported = await client.get(f"/api/themes/builtin/{DEFAULT_KEY}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("plugin.json"))
        assert manifest["kind"] == "theme"
        assert manifest["key"] == DEFAULT_KEY
        assert manifest["entry"] == ""
        assert archive.read("README.md")


async def test_activate_theme_with_overrides(client):
    again = await client.put(
        "/api/themes/active",
        json={
            "key": DEFAULT_KEY,
            "overrides": {
                "background_dim": 0.3,
                "surface_opacity": 0.7,
                "surface_blur": 12,
                "accent": "#ff8800",
                "learn_accent": "#22d3ee",
            },
        },
    )
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["key"] == DEFAULT_KEY
    assert body["overrides"]["surface_opacity"] == 0.7
    # 编辑 / 学习模式强调色独立保存。
    assert body["overrides"]["accent"] == "#ff8800"
    assert body["overrides"]["learn_accent"] == "#22d3ee"

    active = await client.get("/api/themes/active")
    assert active.status_code == 200
    assert active.json()["overrides"]["surface_blur"] == 12

    # 传空对象清空覆盖值；不传则保留。
    kept = await client.put("/api/themes/active", json={"key": DEFAULT_KEY})
    assert kept.json()["overrides"]["surface_opacity"] == 0.7
    cleared = await client.put(
        "/api/themes/active", json={"key": DEFAULT_KEY, "overrides": {}}
    )
    cleared_overrides = cleared.json()["overrides"]
    assert cleared_overrides["surface_opacity"] is None
    assert cleared_overrides["accent"] is None
    assert cleared_overrides["learn_accent"] is None
    assert cleared_overrides["background_image"] == ""


async def test_theme_override_validation(client):
    too_transparent = await client.put(
        "/api/themes/active",
        json={"key": DEFAULT_KEY, "overrides": {"surface_opacity": 0.1}},
    )
    assert too_transparent.status_code == 422

    bad_accent = await client.put(
        "/api/themes/active",
        json={"key": DEFAULT_KEY, "overrides": {"accent": "red"}},
    )
    assert bad_accent.status_code == 422

    bad_learn_accent = await client.put(
        "/api/themes/active",
        json={"key": DEFAULT_KEY, "overrides": {"learn_accent": "green"}},
    )
    assert bad_learn_accent.status_code == 422

    bad_background = await client.put(
        "/api/themes/active",
        json={"key": DEFAULT_KEY, "overrides": {"background_image": "javascript:alert(1)"}},
    )
    assert bad_background.status_code == 422


async def test_import_activate_export_and_delete(client, theme_plugin):
    key = theme_plugin["key"]
    assert theme_plugin["builtin"] is False
    assert "/style.css?v=" in theme_plugin["style_url"]
    assert theme_plugin["preview_url"].endswith("/asset/assets/preview.svg")

    listed = await client.get("/api/themes")
    row = next(item for item in listed.json() if item["key"] == key)
    assert row["theme"]["mode"] == "dark"
    assert row["theme"]["surface"]["opacity"] == 0.8

    activated = await client.put("/api/themes/active", json={"key": key, "overrides": {}})
    assert activated.status_code == 200, activated.text
    active = activated.json()
    assert active["key"] == key
    assert active["builtin"] is False
    assert active["asset_base_url"].startswith("/api/plugins/")
    assert active["style_url"]
    assert active["theme"]["colors"]["accent"] == "#5eead4"

    exported = await client.get(f"/api/plugins/{theme_plugin['id']}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        names = set(archive.namelist())
        assert "plugin.json" in names
        assert "theme.css" in names
        assert "assets/bg.svg" in names
        manifest = json.loads(archive.read("plugin.json"))
        assert manifest["kind"] == "theme"
        source_theme = theme_manifest(key)["theme"]
        assert manifest["theme"]["mode"] == "dark"
        assert manifest["theme"]["colors"] == source_theme["colors"]
        assert manifest["theme"]["background"] == source_theme["background"]
        assert manifest["theme"]["surface"]["opacity"] == 0.8
        assert manifest["theme"]["surface"]["blur"] == 10

    disabled = await client.patch(
        f"/api/plugins/{theme_plugin['id']}", json={"enabled": False}
    )
    assert disabled.status_code == 200
    # 停用当前主题后回落到内置主题，覆盖值一并清空。
    fallback = await client.get("/api/themes/active")
    body = fallback.json()
    assert body["key"] == DEFAULT_KEY
    assert body["builtin"] is True
    assert body["overrides"]["surface_opacity"] is None
    assert body["overrides"]["background_image"] == ""

    deleted = await client.delete(f"/api/plugins/{theme_plugin['id']}")
    assert deleted.status_code == 204


async def test_inspect_rejects_component_package(client):
    component = {
        "manifest_version": 1,
        "kind": "component",
        "key": f"pytest-component-{uuid.uuid4().hex[:6]}",
        "name": "组件",
        "version": "1.0.0",
        "entry": "index.js",
        "blocks": [{"type": "box", "label": "盒子"}],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(component))
        archive.writestr("index.js", "export function setup() { return {} }\n")
    resp = await client.post(
        "/api/themes/inspect",
        files={"file": ("component.zip", buffer.getvalue(), "application/zip")},
    )
    assert resp.status_code == 400
    assert "kind" in resp.json()["detail"]


async def test_theme_inspect_returns_palette(client):
    key = f"inspect-theme-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/themes/inspect",
        files={
            "file": (
                "aurora.zip",
                make_theme_zip(theme_manifest(key)),
                "application/zip",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "theme"
    assert data["key"] == key
    assert data["theme"]["mode"] == "dark"
    assert data["theme"]["colors"]["accent"] == "#5eead4"
    assert data["has_script"] is False
    assert data["has_style"] is True
    assert data["asset_count"] == 2


async def test_theme_spec_and_dev_kit(client):
    spec = await client.get("/api/themes/spec")
    assert spec.status_code == 200
    body = spec.json()
    assert body["kind"] == "theme"
    assert body["skill"] == "kiwi-theme"
    assert body["example"]["kind"] == "theme"
    assert body["examples"]["theme"]["key"] == body["example"]["key"]
    assert body["dev_kit_url"] == "/api/themes/dev-kit"

    kit = await client.get("/api/themes/dev-kit")
    assert kit.status_code == 200
    assert kit.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(kit.content)) as archive:
        names = set(archive.namelist())
        assert "kiwi-theme-dev-kit/THEME_SPEC.md" in names
        assert "kiwi-theme-dev-kit/skill/kiwi-theme/SKILL.md" in names
        assert "kiwi-theme-dev-kit/examples/themes/aurora/plugin.json" in names
        assert "kiwi-theme-dev-kit/AI_PROMPT.md" in names


async def test_import_requires_colors_or_style(client):
    key = f"empty-theme-{uuid.uuid4().hex[:8]}"
    manifest = theme_manifest(key)
    manifest["style"] = ""
    manifest["theme"]["colors"] = {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest))
    resp = await client.post(
        "/api/themes/import",
        files={"file": ("empty.zip", buffer.getvalue(), "application/zip")},
    )
    assert resp.status_code == 400
