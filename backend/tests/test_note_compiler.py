"""笔记编译：全部笔记类型都能序列化为可编译的 Markdown。"""

from __future__ import annotations

import uuid

from app.db.models import CollectionRow, Note, NoteCollection
from app.services.note_compiler import build_note_compile_markdown

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
        },
        {
            "id": "s2",
            "name": "关键工具和方法",
            "rows": 20,
            "cols": 8,
            "cells": {"A1": {"v": "工具名称"}, "A2": {"v": "WBS"}},
            "colWidths": {},
            "rowHeights": {},
            "merges": [],
        },
    ],
}


def _note(kb_id: str, **kwargs) -> Note:
    payload = {
        "kb_id": uuid.UUID(kb_id),
        "title": "测试笔记",
        "kind": "doc",
        "body_md": "",
        "props_json": {},
    }
    payload.update(kwargs)
    return Note(**payload)


async def test_sheet_note_markdown_serializes_all_sheets(db, kb):
    note = _note(
        kb["id"],
        title="关键模型和分析工具",
        kind="sheet",
        props_json={"sheet": SHEET_WORKBOOK},
    )
    markdown = await build_note_compile_markdown(db, note)
    assert "# 关键模型和分析工具" in markdown
    assert "## 十大知识领域" in markdown
    assert "## 关键工具和方法" in markdown
    # 首行加粗识别为表头，单元格内容按 Markdown 表格保留
    assert "| 领域名称 | 子过程名称 |" in markdown
    assert "| 项目范围管理 | 规划范围管理 |" in markdown
    assert "WBS" in markdown


async def test_sheet_note_markdown_falls_back_to_body(db, kb):
    note = _note(
        kb["id"],
        title="带说明的表格",
        kind="sheet",
        body_md="表格的说明正文",
        props_json={"sheet": {"version": 1, "active": "s1", "sheets": []}},
    )
    assert (await build_note_compile_markdown(db, note)) == "表格的说明正文"


async def test_every_note_kind_produces_markdown(db, kb):
    """文档 / 导入 / 链接 / 画布 / Notebook / 表格都要有可编译内容。"""
    cases = [
        (_note(kb["id"], kind="doc", body_md="文档正文"), "文档正文"),
        (_note(kb["id"], kind="import", body_md="导入正文"), "导入正文"),
        (
            _note(
                kb["id"],
                kind="link",
                props_json={
                    "link": {
                        "url": "https://example.com/g6",
                        "site": "Example",
                        "excerpt": "链接摘要内容",
                    }
                },
            ),
            "链接摘要内容",
        ),
        (
            _note(
                kb["id"],
                kind="canvas",
                props_json={
                    "canvas_doc": {
                        "theme": "engineering",
                        "nodes": [{"id": "n1", "shape": "rect", "text": "画布节点标题"}],
                        "edges": [],
                    }
                },
            ),
            "画布节点标题",
        ),
        (
            _note(
                kb["id"],
                kind="notebook",
                props_json={
                    "notebook_doc": {
                        "language": "python",
                        "cells": [{"type": "code", "source": "print('notebook')"}],
                    }
                },
            ),
            "print('notebook')",
        ),
        (
            _note(kb["id"], kind="sheet", props_json={"sheet": SHEET_WORKBOOK}),
            "项目范围管理",
        ),
    ]
    for note, needle in cases:
        markdown = await build_note_compile_markdown(db, note)
        assert markdown, f"{note.kind} 没有生成可编译内容"
        assert needle in markdown, f"{note.kind} 缺少结构化内容"


async def test_database_note_markdown_includes_rows(db, kb):
    note = _note(kb["id"], title="项目清单", kind="database")
    db.add(note)
    await db.commit()
    await db.refresh(note)
    collection = NoteCollection(
        kb_id=note.kb_id,
        note_id=note.id,
        name="项目清单",
        description="",
        schema_json={"fields": [{"id": "name", "name": "名称", "type": "text"}]},
        views_json=[],
    )
    db.add(collection)
    await db.commit()
    await db.refresh(collection)
    db.add(
        CollectionRow(
            kb_id=note.kb_id,
            collection_id=collection.id,
            data={"name": "块命令与表格"},
            sort_order=0,
        )
    )
    await db.commit()

    markdown = await build_note_compile_markdown(db, note)
    assert "# 项目清单" in markdown
    assert "块命令与表格" in markdown


async def test_compile_endpoint_accepts_sheet_note(client, kb, note_factory):
    note = await note_factory(
        title="关键模型和分析工具",
        kind="sheet",
        props_json={"sheet": SHEET_WORKBOOK},
    )
    resp = await client.post(f"/api/notes/{note['id']}/compile?kb_id={kb['id']}")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["job_id"] and body["source_id"]
