"""笔记搜索：关联 Wiki 页面与素材标题参与命中。"""

from __future__ import annotations

import uuid

from app.db.models.wiki import WikiPage


async def test_search_matches_note_linked_wiki_page(client, db, kb, note_factory):
    """关联页面的正文命中时，笔记本身也要出现在结果里，而不是报 500。"""
    page = WikiPage(
        kb_id=uuid.UUID(kb["id"]),
        slug=f"book-{uuid.uuid4().hex[:8]}",
        title="阅读清单",
        body_md="book 相关正文，只存在于关联的 Wiki 页面中。",
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)

    linked = await note_factory(
        title="关联 Wiki 的笔记",
        props_json={"wiki_page_id": str(page.id)},
    )
    unrelated = await note_factory(title="普通笔记")

    resp = await client.get(f"/api/notes/search?kb_id={kb['id']}&q=book&status=all&limit=100")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    ids = {item["note"]["id"] for item in items}
    assert linked["id"] in ids
    assert unrelated["id"] not in ids

    hit = next(item for item in items if item["note"]["id"] == linked["id"])
    assert "wiki" in hit["matched_fields"]
    assert "book" in hit["snippet"]


SHEET_WORKBOOK = {
    "version": 1,
    "active": "s1",
    "sheets": [
        {
            "id": "s1",
            "name": "十大知识领域",
            "rows": 100,
            "cols": 26,
            "cells": {
                "A1": {"v": "领域名称", "s": {"bold": True}},
                "B1": {"v": "子过程名称", "s": {"bold": True}},
                "A2": {"v": "项目范围管理"},
                "B2": {"v": "规划范围管理"},
            },
            "colWidths": {},
            "rowHeights": {},
            "merges": [],
        }
    ],
}


async def test_search_matches_sheet_cell_content(client, kb, note_factory):
    """表格笔记内容在 props_json 里，也要能命中并给出单元格片段。"""
    sheet = await note_factory(
        title="关键模型和分析工具",
        kind="sheet",
        props_json={"sheet": SHEET_WORKBOOK},
    )
    other = await note_factory(title="无关文档", body_md="只有普通正文")

    resp = await client.get(
        f"/api/notes/search?kb_id={kb['id']}&q=项目范围管理&status=all&limit=100"
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    hit = next((item for item in items if item["note"]["id"] == sheet["id"]), None)
    assert hit is not None
    assert "content" in hit["matched_fields"]
    assert "项目范围管理" in hit["snippet"]
    assert other["id"] not in {item["note"]["id"] for item in items}


async def test_search_matches_database_row_content(client, kb, note_factory):
    """数据表记录不在正文中，按行数据命中后要返回所属数据表笔记。"""
    database = await note_factory(title="项目清单", kind="database")
    row = await client.post(
        f"/api/notes/{database['id']}/rows?kb_id={kb['id']}",
        json={"data": {"name": "块命令与表格"}},
    )
    assert row.status_code == 201, row.text
    other = await note_factory(title="无关文档", body_md="只有普通正文")

    resp = await client.get(f"/api/notes/search?kb_id={kb['id']}&q=块命令&status=all&limit=100")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    hit = next((item for item in items if item["note"]["id"] == database["id"]), None)
    assert hit is not None
    assert "content" in hit["matched_fields"]
    assert "块命令与表格" in hit["snippet"]
    assert other["id"] not in {item["note"]["id"] for item in items}
