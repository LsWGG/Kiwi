"""笔记内嵌附件读取的纯逻辑测试（不依赖数据库 / 向量库）。"""

from __future__ import annotations

import json

from app.services.attachment_content import (
    embedded_file_blocks,
    format_attachments_for_context,
    read_embedded_attachments,
)


def block(payload: dict, quote: bool = False, fence: str = "```") -> str:
    body = f"{fence}kiwi-embed\n{json.dumps(payload, ensure_ascii=False)}\n{fence}"
    if not quote:
        return body
    return "\n".join(f"> {line}" for line in body.splitlines())


def make_media(tmp_path, name: str, content: str) -> dict:
    media = tmp_path / "media" / "kb"
    media.mkdir(parents=True, exist_ok=True)
    target = media / name
    target.write_text(content, encoding="utf-8")
    return {
        "kind": "file",
        "url": f"/media/kb/{name}",
        "filename": name,
        "contentType": "text/x-python",
        "size": len(content.encode("utf-8")),
    }


def test_extracts_file_blocks_with_quote_and_tilde_fences():
    normal = block({"kind": "file", "url": "/media/kb/a.py"})
    quoted = block({"kind": "file", "url": "/media/kb/b.py"}, quote=True)
    tilde = block({"kind": "file", "url": "/media/kb/c.py"}, fence="~~~")
    body = f"{normal}\n\n{quoted}\n\n{tilde}"
    urls = [item["url"] for item in embedded_file_blocks(body)]
    assert urls == ["/media/kb/a.py", "/media/kb/b.py", "/media/kb/c.py"]


def test_extracts_blocks_nested_in_list_items():
    # 实际笔记里附件常放在有序列表项下，围栏与 JSON 都带 3 空格缩进。
    body = (
        "1. 网片分辨率处理脚本\n\n"
        "   ```kiwi-embed\n"
        '   {"kind":"file","url":"/media/kb/resize_images.py",'
        '"filename":"resize_images.py","contentType":"text/x-python"}\n'
        "   ```\n"
    )
    blocks = embedded_file_blocks(body)
    assert [item["url"] for item in blocks] == ["/media/kb/resize_images.py"]


def test_ignores_link_cards_remote_urls_and_broken_json():
    body = "\n\n".join(
        [
            block({"kind": "link", "url": "https://example.com"}),
            block({"kind": "file", "url": "https://example.com/a.py"}),
            "```kiwi-embed\n{not json}\n```",
            "```python\nprint('hi')\n```",
            block({"kind": "file", "url": "/media/kb/a.py"}),
            block({"kind": "file", "url": "/media/kb/a.py"}),
        ]
    )
    assert [item["url"] for item in embedded_file_blocks(body)] == ["/media/kb/a.py"]


def test_reads_uploaded_text_file_and_truncates(tmp_path):
    payload = make_media(tmp_path, "resize_images.py", "print('resize')\n" * 20)
    body = block(payload)
    items = read_embedded_attachments(
        body, media_root=tmp_path / "media", max_chars=40
    )
    assert len(items) == 1
    item = items[0]
    assert item.filename == "resize_images.py"
    assert item.language == "python"
    assert item.text == ("print('resize')\n" * 20)[:40]
    assert item.truncated is True


def test_query_prioritizes_named_attachment(tmp_path):
    first = make_media(tmp_path, "alpha.py", "alpha = 1\n")
    second = make_media(tmp_path, "beta.py", "beta = 2\n")
    body = f"{block(first)}\n\n{block(second)}"
    items = read_embedded_attachments(
        body, query="帮我梳理 beta.py 的逻辑", media_root=tmp_path / "media", max_files=1
    )
    assert [item.filename for item in items] == ["beta.py"]


def test_skips_traversal_missing_and_binary_attachments(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    media = tmp_path / "media"
    (media / "kb").mkdir(parents=True)
    missing = {
        "kind": "file",
        "url": "/media/kb/missing.py",
        "filename": "missing.py",
    }
    traversal = {
        "kind": "file",
        "url": "/media/../secret.txt",
        "filename": "secret.txt",
    }
    image = {"kind": "file", "url": "/media/kb/a.png", "filename": "a.png"}
    (media / "kb" / "a.png").write_bytes(b"\x89PNG\r\n")
    body = f"{block(missing)}\n\n{block(traversal)}\n\n{block(image)}"
    assert read_embedded_attachments(body, media_root=media) == []


def test_total_budget_stops_after_first_file(tmp_path):
    first = make_media(tmp_path, "a.py", "a" * 30)
    second = make_media(tmp_path, "b.py", "b" * 30)
    body = f"{block(first)}\n\n{block(second)}"
    items = read_embedded_attachments(
        body,
        media_root=tmp_path / "media",
        max_chars=20,
        total_chars=20,
    )
    assert [item.filename for item in items] == ["a.py"]


def test_formats_context_with_filename_metadata_and_fence(tmp_path):
    payload = make_media(tmp_path, "resize_images.py", "def run():\n    pass\n")
    items = read_embedded_attachments(
        block(payload), media_root=tmp_path / "media"
    )
    text = format_attachments_for_context(items)
    assert "resize_images.py" in text
    assert "text/x-python" in text
    assert "```python" in text
    assert "def run():" in text
