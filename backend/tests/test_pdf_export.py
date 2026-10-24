"""文本类笔记 PDF 导出：中文排版、Markdown 结构、上锁与文件名。"""

from __future__ import annotations

import pymupdf


def _pdf_text(content: bytes) -> str:
    doc = pymupdf.open(stream=content, filetype="pdf")
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


async def test_export_text_note_pdf(client, kb, note_factory):
    note = await note_factory(
        title="PDF 导出回归",
        body_md=(
            "# 小节标题\n\n"
            "中文正文包含 **加粗** 与 `行内代码`。\n\n"
            "- 第一项\n- 第二项\n\n"
            "| 名称 | 数值 |\n| --- | --- |\n| 猕猴桃 | 42 |\n\n"
            "```python\nprint('你好')\n```\n"
        ),
    )

    resp = await client.get(f"/api/notes/{note['id']}/export/pdf?kb_id={kb['id']}")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    assert "filename*=UTF-8''" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF-")

    text = _pdf_text(resp.content)
    assert "PDF 导出回归" in text
    assert "小节标题" in text
    assert "中文正文" in text
    assert "第一项" in text
    assert "猕猴桃" in text
    assert "42" in text
    assert "print" in text

    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    try:
        assert doc.page_count >= 1
        assert doc.metadata["title"] == "PDF 导出回归"
        assert doc.metadata["creator"] == "Kiwi"
    finally:
        doc.close()


async def test_export_locked_note_pdf_requires_token(client, kb, note_factory):
    note = await note_factory(title="上锁 PDF", body_md="机密正文 alpha")
    lock = await client.post(
        f"/api/notes/{note['id']}/lock?kb_id={kb['id']}",
        json={"password": "test1234", "hint": "测试", "encrypt": True},
    )
    assert lock.status_code == 200, lock.text
    token = lock.json()["token"]

    denied = await client.get(f"/api/notes/{note['id']}/export/pdf?kb_id={kb['id']}")
    assert denied.status_code == 403
    assert "上锁" in denied.json()["detail"]

    allowed = await client.get(
        f"/api/notes/{note['id']}/export/pdf?kb_id={kb['id']}",
        headers={"X-Note-Token": token},
    )
    assert allowed.status_code == 200, allowed.text
    assert "机密正文 alpha" in _pdf_text(allowed.content)


async def test_export_missing_note_pdf_404(client, kb):
    resp = await client.get(
        f"/api/notes/00000000-0000-0000-0000-000000000000/export/pdf?kb_id={kb['id']}"
    )
    assert resp.status_code == 404
