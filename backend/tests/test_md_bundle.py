"""压缩包版 Markdown：md + 图片 / 附件目录导入与引用重写。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from app.config import settings

PNG = b"\x89PNG\r\n\x1a\nkiwi-md-bundle"
PDF = b"%PDF-1.4\n% test attachment\n"

MARKDOWN = """---
title: 压缩包笔记
---

# 压缩包导入测试

![图一](<images/图 1.png> "图片标题")
![图二](images/pic2.png)
附件：[资料](files/%E8%AF%B4%E6%98%8E.pdf)
<img src="./images/pic2.png" />

引用式：![引用图][cover]

[cover]: images/cover.webp

双链：![[images/cover.webp|300]]

外部链接：[官网](https://example.com/docs)
"""


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def _cleanup_media(kb_id: str) -> None:
    root = Path(settings.upload_dir) / "media" / kb_id
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_file():
            child.unlink()
    try:
        root.rmdir()
    except OSError:
        pass


def _bundle() -> bytes:
    return _zip(
        {
            "notes/demo.md": MARKDOWN.encode("utf-8"),
            "notes/images/图 1.png": PNG,
            "notes/images/pic2.png": PNG + b"2",
            "notes/images/cover.webp": b"RIFF0000WEBP",
            "notes/files/说明.pdf": PDF,
            "__MACOSX/notes/._demo.md": b"junk",
            "notes/.DS_Store": b"junk",
        }
    )


def _assert_rewritten(markdown: str) -> None:
    assert "/media/" in markdown
    assert "](images/" not in markdown
    assert "](<images/" not in markdown
    assert "(./images/" not in markdown
    assert "](files/" not in markdown
    assert "[[images/" not in markdown
    # 外部链接保持原样
    assert "](https://example.com/docs)" in markdown


async def test_import_zip_markdown_bundle(client, kb) -> None:
    kb_id = kb["id"]
    try:
        resp = await client.post(
            f"/api/notes/import?kb_id={kb_id}",
            files={"file": ("demo.zip", _bundle(), "application/zip")},
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        note = data["note"]
        assert data["job_id"] is None
        assert note["kind"] == "doc"
        # frontmatter 的 title 优先于一级标题
        assert note["title"] == "压缩包笔记"
        assert note["props_json"]["import"]["attachment_count"] == 4
        _assert_rewritten(note["body_md"])

        attachments = await client.get(
            f"/api/attachments?kb_id={kb_id}&note_id={note['id']}"
        )
        assert attachments.status_code == 200, attachments.text
        items = attachments.json()
        assert len(items) == 4
        names = {item["filename"] for item in items}
        assert {"图 1.png", "pic2.png", "cover.webp", "说明.pdf"} <= names

        # 重写后的 URL 必须真实可访问
        for item in items:
            media = await client.get(item["url"])
            assert media.status_code == 200, item["url"]
    finally:
        _cleanup_media(kb_id)


async def test_import_zip_without_markdown_is_rejected(client, kb) -> None:
    kb_id = kb["id"]
    payload = _zip({"images/a.png": PNG})
    try:
        resp = await client.post(
            f"/api/notes/import?kb_id={kb_id}",
            files={"file": ("assets.zip", payload, "application/zip")},
        )
        assert resp.status_code == 422, resp.text
        assert "Markdown" in resp.json()["detail"]
    finally:
        _cleanup_media(kb_id)


async def test_import_zip_skips_unsafe_paths(client, kb) -> None:
    kb_id = kb["id"]
    payload = _zip(
        {
            "demo.md": "# 安全测试\n\n![x](../evil.png)\n".encode(),
            "../evil.png": b"evil",
        }
    )
    try:
        resp = await client.post(
            f"/api/notes/import?kb_id={kb_id}",
            files={"file": ("safe.zip", payload, "application/zip")},
        )
        assert resp.status_code == 202, resp.text
        note = resp.json()["note"]
        assert note["title"] == "安全测试"
        assert "../evil.png" in note["body_md"]  # 无法解析的引用保持原样
        attachments = await client.get(
            f"/api/attachments?kb_id={kb_id}&note_id={note['id']}"
        )
        assert attachments.json() == []
    finally:
        _cleanup_media(kb_id)


async def test_attachments_md_bundle_inserts_into_existing_note(
    client, kb, note_factory
) -> None:
    kb_id = kb["id"]
    note = await note_factory()
    try:
        resp = await client.post(
            f"/api/attachments/md-bundle?kb_id={kb_id}&note_id={note['id']}",
            files={"file": ("demo.zip", _bundle(), "application/zip")},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["found"] is True
        assert data["title"] == "压缩包笔记"
        assert data["main_entry"] == "notes/demo.md"
        assert len(data["attachments"]) == 4
        _assert_rewritten(data["markdown"])

        listed = await client.get(
            f"/api/attachments?kb_id={kb_id}&note_id={note['id']}"
        )
        bound = listed.json()
        assert len(bound) == 4
        assert all(item["note_id"] == note["id"] for item in bound)
    finally:
        _cleanup_media(kb_id)


async def test_attachments_md_bundle_without_markdown_falls_back(
    client, kb, note_factory
) -> None:
    kb_id = kb["id"]
    note = await note_factory()
    try:
        resp = await client.post(
            f"/api/attachments/md-bundle?kb_id={kb_id}&note_id={note['id']}",
            files={
                "file": (
                    "assets.zip",
                    _zip({"images/a.png": PNG}),
                    "application/zip",
                )
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["found"] is False
        listed = await client.get(
            f"/api/attachments?kb_id={kb_id}&note_id={note['id']}"
        )
        assert listed.json() == []
    finally:
        _cleanup_media(kb_id)


async def test_md_bundle_rejects_non_zip(client, kb, note_factory) -> None:
    kb_id = kb["id"]
    note = await note_factory()
    resp = await client.post(
        f"/api/attachments/md-bundle?kb_id={kb_id}&note_id={note['id']}",
        files={"file": ("demo.md", b"# hi", "text/markdown")},
    )
    assert resp.status_code == 415, resp.text
