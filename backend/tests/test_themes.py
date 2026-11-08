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


# ---------------------------------------------------------------------------
# 内置主题：经典紫 + 极光
# ---------------------------------------------------------------------------

AURORA_KEY = "aurora"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
GIF_BYTES = b"GIF89a" + b"\x00" * 64
MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64


async def test_builtin_themes_are_classic_and_aurora(client):
    resp = await client.get("/api/themes")
    assert resp.status_code == 200
    builtins = [item for item in resp.json() if item["builtin"]]
    # 系统只内置 经典紫 与 极光，其余主题必须由用户自行安装。
    assert {item["key"] for item in builtins} == {DEFAULT_KEY, AURORA_KEY}

    aurora = next(item for item in builtins if item["key"] == AURORA_KEY)
    assert aurora["style_url"] == "/api/themes/builtin/aurora/style.css"
    assert aurora["asset_base_url"] == "/api/themes/builtin/aurora/asset/"
    assert aurora["preview_url"] == (
        "/api/themes/builtin/aurora/asset/assets/preview.svg"
    )
    assert set(aurora["assets"]) == {"assets/aurora.svg", "assets/preview.svg"}

    style = await client.get(aurora["style_url"])
    assert style.status_code == 200
    assert style.headers["content-type"].startswith("text/css")
    assert "html[data-kiwi-theme='aurora']" in style.text

    preview = await client.get(aurora["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/svg+xml")
    assert preview.content.startswith(b"<svg")

    background = await client.get(
        f"{aurora['asset_base_url']}assets/aurora.svg"
    )
    assert background.status_code == 200
    assert background.content.startswith(b"<svg")

    missing = await client.get(f"{aurora['asset_base_url']}assets/nope.svg")
    assert missing.status_code == 404


async def test_builtin_aurora_export_contains_style_and_assets(client):
    exported = await client.get("/api/themes/builtin/aurora/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        names = set(archive.namelist())
        assert {"plugin.json", "theme.css", "README.md"} <= names
        assert "assets/aurora.svg" in names
        assert "assets/preview.svg" in names
        manifest = json.loads(archive.read("plugin.json"))
        assert manifest["key"] == AURORA_KEY
        assert manifest["theme"]["background"]["image"] == "assets/aurora.svg"


async def test_activate_builtin_aurora(client):
    resp = await client.put(
        "/api/themes/active", json={"key": AURORA_KEY, "overrides": {}}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == AURORA_KEY
    assert body["builtin"] is True
    assert body["style_url"] == "/api/themes/builtin/aurora/style.css"
    assert body["asset_base_url"] == "/api/themes/builtin/aurora/asset/"
    assert body["theme"]["mode"] == "dark"

    active = await client.get("/api/themes/active")
    assert active.json()["key"] == AURORA_KEY


async def test_gallery_order_active_then_builtin_then_installed(client, theme_plugin):
    activated = await client.put(
        "/api/themes/active", json={"key": theme_plugin["key"], "overrides": {}}
    )
    assert activated.status_code == 200, activated.text

    # 再装一个未启用的主题，验证「已安装」组排在全部内置主题之后。
    other_key = f"pytest-theme-{uuid.uuid4().hex[:8]}"
    imported = await client.post(
        "/api/themes/import",
        files={
            "file": (
                "other.zip",
                make_theme_zip(theme_manifest(other_key)),
                "application/zip",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    other_id = imported.json()["id"]

    try:
        rows = (await client.get("/api/themes")).json()
        assert rows[0]["key"] == theme_plugin["key"]
        assert rows[0]["active"] is True
        assert all(item["active"] is False for item in rows[1:])

        builtin_indexes = [
            index for index, item in enumerate(rows) if item["builtin"]
        ]
        installed_indexes = [
            index
            for index, item in enumerate(rows)
            if not item["builtin"] and not item["active"]
        ]
        assert builtin_indexes
        assert installed_indexes
        assert max(builtin_indexes) < min(installed_indexes)
        assert any(item["key"] == other_key for item in rows)

        builtin_names = [item["name"] for item in rows if item["builtin"]]
        assert builtin_names == sorted(builtin_names, key=str.casefold)
    finally:
        await client.delete(f"/api/plugins/{other_id}")


async def test_gallery_hides_legacy_duplicate_of_builtin(client, db):
    from sqlalchemy import select

    from app.db.models import Plugin

    existing = (
        await db.execute(select(Plugin).where(Plugin.key == AURORA_KEY))
    ).scalar_one_or_none()
    if existing is not None:
        pytest.skip("测试库已有 aurora 安装记录")

    plugin = Plugin(
        key=AURORA_KEY,
        name="旧版极光",
        kind="theme",
        manifest={"theme": theme_manifest(AURORA_KEY)["theme"]},
    )
    db.add(plugin)
    await db.commit()
    try:
        rows = (await client.get("/api/themes")).json()
        matches = [item for item in rows if item["key"] == AURORA_KEY]
        assert len(matches) == 1
        assert matches[0]["builtin"] is True
    finally:
        await db.delete(plugin)
        await db.commit()


# ---------------------------------------------------------------------------
# 自定义背景：100MB 图片 / 动图 / 视频
# ---------------------------------------------------------------------------


@pytest.fixture
async def upload_background(client):
    urls: list[str] = []

    async def upload(
        data: bytes,
        *,
        filename: str = "wallpaper.png",
        content_type: str = "image/png",
    ) -> dict:
        resp = await client.post(
            "/api/themes/background",
            files={"file": (filename, data, content_type)},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        urls.append(body["url"])
        return body

    yield upload

    # 先清空覆盖值，否则仍被引用的文件不允许删除。
    await client.put(
        "/api/themes/active", json={"key": DEFAULT_KEY, "overrides": {}}
    )
    for url in urls:
        await client.delete("/api/themes/background", params={"url": url})


async def test_background_upload_image_and_serve(client, upload_background):
    body = await upload_background(PNG_BYTES)
    assert body["kind"] == "image"
    assert body["content_type"] == "image/png"
    assert body["size"] == len(PNG_BYTES)
    assert body["url"].startswith("/media/theme-backgrounds/")
    assert body["url"].endswith(".png")

    served = await client.get(body["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == PNG_BYTES


async def test_background_upload_accepts_gif_and_video(client, upload_background):
    gif = await upload_background(GIF_BYTES, filename="loop.gif", content_type="image/gif")
    assert gif["kind"] == "image"
    assert gif["content_type"] == "image/gif"
    assert gif["url"].endswith(".gif")

    video = await upload_background(
        MP4_BYTES, filename="window.mp4", content_type="video/mp4"
    )
    assert video["kind"] == "video"
    assert video["content_type"] == "video/mp4"
    assert video["size"] == len(MP4_BYTES)
    assert video["url"].endswith(".mp4")

    served = await client.get(video["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "video/mp4"


async def test_background_upload_rejects_unknown_and_oversize(client, monkeypatch):
    unsupported = await client.post(
        "/api/themes/background",
        files={"file": ("evil.svg", b"<svg onload=alert(1)>", "image/svg+xml")},
    )
    assert unsupported.status_code == 415

    from app.services import theme_backgrounds

    monkeypatch.setattr(theme_backgrounds, "MAX_BACKGROUND_BYTES", 16)
    oversize = await client.post(
        "/api/themes/background",
        files={"file": ("big.png", PNG_BYTES, "image/png")},
    )
    assert oversize.status_code == 413


async def test_background_video_override_validation(client):
    for value in ("data:video/mp4;base64,AAAA", "javascript:alert(1)"):
        resp = await client.put(
            "/api/themes/active",
            json={"key": DEFAULT_KEY, "overrides": {"background_video": value}},
        )
        assert resp.status_code == 422, resp.text

    url = "/media/theme-backgrounds/demo.mp4"
    saved = await client.put(
        "/api/themes/active",
        json={"key": DEFAULT_KEY, "overrides": {"background_video": url}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["overrides"]["background_video"] == url


async def test_replacing_background_prunes_previous_file(
    client, upload_background
):
    first = await upload_background(PNG_BYTES)
    second = await upload_background(PNG_BYTES, filename="second.png")
    assert first["url"] != second["url"]

    saved = await client.put(
        "/api/themes/active",
        json={
            "key": DEFAULT_KEY,
            "overrides": {"background_image": first["url"]},
        },
    )
    assert saved.status_code == 200, saved.text
    assert (await client.get(first["url"])).status_code == 200

    replaced = await client.put(
        "/api/themes/active",
        json={
            "key": DEFAULT_KEY,
            "overrides": {"background_image": second["url"]},
        },
    )
    assert replaced.status_code == 200, replaced.text
    assert (await client.get(first["url"])).status_code == 404
    assert (await client.get(second["url"])).status_code == 200


async def test_background_delete_blocks_active_file(client, upload_background):
    body = await upload_background(PNG_BYTES)
    saved = await client.put(
        "/api/themes/active",
        json={
            "key": DEFAULT_KEY,
            "overrides": {"background_image": body["url"]},
        },
    )
    assert saved.status_code == 200, saved.text

    blocked = await client.delete(
        "/api/themes/background", params={"url": body["url"]}
    )
    assert blocked.status_code == 400

    cleared = await client.put(
        "/api/themes/active", json={"key": DEFAULT_KEY, "overrides": {}}
    )
    assert cleared.status_code == 200
    # 清空覆盖值时后端会顺带删除不再引用的文件。
    gone = await client.delete(
        "/api/themes/background", params={"url": body["url"]}
    )
    assert gone.status_code == 404
