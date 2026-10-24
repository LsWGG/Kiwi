"""笔记编译资格：哪些工作区节点应进入 Wiki 编译。

规则（与前端 `noteCompileEligibility` 保持一致）：

- 数据表行笔记随所属数据表编译，不单独提交；
- 「待办汇总」由 todo_sync 自动维护，不属于知识正文；
- 只读导入材料（文件 / 链接）只是素材快照，编辑与编译都会先转成普通笔记；
- 其余文档 / 数据表 / 链接 / 导入 / 画布 / Notebook / 表格都参与编译。
"""

from __future__ import annotations

from app.db.models import Note

SKIP_COLLECTION_ROW = "collection_row"
SKIP_TODO_HUB = "todo_hub"
SKIP_READONLY_IMPORT = "readonly_import"

SKIP_LABELS = {
    SKIP_COLLECTION_ROW: "数据表行笔记随数据表一起编译，无需单独编译",
    SKIP_TODO_HUB: "待办汇总由系统自动维护，无需编译",
    SKIP_READONLY_IMPORT: "只读导入材料无需编译，可转为可编辑笔记后再编译",
}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def note_compile_skip_reason(note: Note) -> str | None:
    """返回跳过编译的原因 key；可编译时返回 None。"""
    props = note.props_json or {}
    if props.get("collection_row_id"):
        return SKIP_COLLECTION_ROW
    if _truthy(props.get("todo_hub")):
        return SKIP_TODO_HUB
    if _truthy(props.get("readonly")):
        return SKIP_READONLY_IMPORT
    import_meta = props.get("import")
    if isinstance(import_meta, dict) and _truthy(import_meta.get("readonly")):
        return SKIP_READONLY_IMPORT
    return None


def note_compile_eligible(note: Note) -> bool:
    return note_compile_skip_reason(note) is None


def note_compile_skip_label(note: Note) -> str | None:
    reason = note_compile_skip_reason(note)
    return SKIP_LABELS.get(reason) if reason else None
