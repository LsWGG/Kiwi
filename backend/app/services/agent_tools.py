"""Agent 工具注册表：定义、参数校验与执行。

工具不再写死在 Agent 循环里，而是注册成带 JSON Schema 的 ``ToolDef``：

- 内置工具在本模块用 ``@_tool`` 注册，参数模型同时生成给 LLM 的 schema；
- 外部工具由 MCP 服务动态发现（``app.mcp.client``）；
- Agent 只依赖 ``Toolbox``，因此新增工具不需要改循环代码。

问答的 Agent 循环只会自动执行只读工具；所有写操作必须先进入
``agent_actions`` 的待确认队列，由用户在界面上批准后才执行。工具全部限定在
当前知识库内，上锁笔记不可读也不可改，永久删除不开放。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Note, NoteFolder, NoteTemplate
from app.mcp import Toolbox, ToolDef, ToolError
from app.mcp.client import call_external_tool, external_tools
from app.mcp.types import field_labels
from app.routers.note_databases import (
    create_row as create_row_route,
)
from app.routers.note_databases import (
    delete_row as delete_row_route,
)
from app.routers.note_databases import (
    list_rows as list_rows_route,
)
from app.routers.note_databases import (
    update_row as update_row_route,
)
from app.routers.notes_crud import create_note as create_note_route
from app.routers.notes_crud import update_note as update_note_route
from app.routers.notes_lifecycle import delete_note as delete_note_route
from app.routers.notes_search import search_notes as search_notes_route
from app.routers.notes_templates import _ensure_builtin_templates
from app.routers.notes_tree import create_folder as create_folder_route
from app.routers.notes_tree import delete_folder as delete_folder_route
from app.routers.notes_tree import update_folder as update_folder_route
from app.schemas.note import (
    NoteCreate,
    NoteFolderCreate,
    NoteFolderUpdate,
    NoteUpdate,
)
from app.schemas.note_database import RowCreate, RowUpdate
from app.services.link_fetcher import LinkFetchError, SSRFError, fetch_and_extract
from app.services.note_database import ensure_collection

logger = logging.getLogger("kiwi.agent.tools")

MAX_NOTE_BODY = 400_000
# 上下文窗口已放宽到 1M，全文读取不再按 12k 截断；仍保留上限，
# 防止单篇超长笔记把工具结果与上下文挤满。
MAX_RESULT_NOTE_BODY = 40_000
# 网页正文通常比笔记长，但超过这个长度仍会挤占上下文；
# 截断时明确标记，避免模型把不完整正文当成全文写入笔记。
MAX_RESULT_WEB_BODY = 120_000


class SearchNotesArgs(BaseModel):
    query: str = Field(
        default="",
        max_length=200,
        title="关键词",
        description="搜索关键词，匹配标题、正文、标签与数据表文本；留空表示只按其他条件筛选。",
    )
    kind: str | None = Field(
        default=None,
        max_length=20,
        title="笔记类型",
        description="可选：doc（文档）、database（数据表）、canvas（画布）、sheet（表格）、notebook（手账）。",
    )
    folder_id: uuid.UUID | None = Field(
        default=None, title="分组", description="只搜索该分组内的笔记；不传表示不限分组。"
    )
    created_from: datetime | None = Field(
        default=None,
        title="创建起",
        description="创建时间下限，ISO 8601 日期或时间，例如 2026-11-16 或 2026-11-16T09:00:00。",
    )
    created_to: datetime | None = Field(
        default=None,
        title="创建止",
        description="创建时间上限；只写日期时包含当天（到 23:59:59）。",
    )
    updated_from: datetime | None = Field(
        default=None,
        title="更新起",
        description="更新时间下限。问「这周 / 最近做了什么」时用它限定时间范围。",
    )
    updated_to: datetime | None = Field(
        default=None,
        title="更新止",
        description="更新时间上限；只写日期时包含当天（到 23:59:59）。",
    )
    limit: int = Field(
        default=20, ge=1, le=50, title="返回条数", description="最多返回多少条，1-50，默认 20。"
    )


class ListNotesArgs(BaseModel):
    folder_id: uuid.UUID | None = Field(
        default=None, title="分组", description="只列出该分组内的笔记；不传表示不限分组。"
    )
    kind: str | None = Field(
        default=None,
        max_length=20,
        title="笔记类型",
        description="可选：doc / database / canvas / sheet / notebook。",
    )
    created_from: datetime | None = Field(
        default=None,
        title="创建起",
        description="创建时间下限，ISO 8601 日期或时间。",
    )
    created_to: datetime | None = Field(
        default=None,
        title="创建止",
        description="创建时间上限；只写日期时包含当天。",
    )
    updated_from: datetime | None = Field(
        default=None,
        title="更新起",
        description="更新时间下限。按时间了解最近改动时优先使用。",
    )
    updated_to: datetime | None = Field(
        default=None,
        title="更新止",
        description="更新时间上限；只写日期时包含当天。",
    )
    limit: int = Field(
        default=50, ge=1, le=100, title="返回条数", description="最多返回多少条，1-100，默认 50。"
    )
    offset: int = Field(
        default=0, ge=0, title="偏移", description="跳过多少条，用于翻页；默认 0。"
    )


class GetNoteArgs(BaseModel):
    note_id: uuid.UUID = Field(
        title="笔记",
        description="笔记 UUID，必须来自 list_notes / search_notes 的返回结果，不要编造。",
    )


class FetchUrlArgs(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        title="网页链接",
        description="要读取的 http/https 公开网页地址，例如 https://example.com/article。",
    )


class ListFoldersArgs(BaseModel):
    pass


class ListDatabasesArgs(BaseModel):
    pass


class ListTemplatesArgs(BaseModel):
    query: str = Field(
        default="",
        max_length=100,
        title="关键词",
        description="按模板名称或说明过滤，例如「旅游规划」；留空返回全部模板。",
    )


class GetTemplateArgs(BaseModel):
    template_id: uuid.UUID | None = Field(
        default=None,
        title="模板 ID",
        description="模板 UUID，来自 list_templates；与 name 二选一。",
    )
    name: str = Field(
        default="",
        max_length=200,
        title="模板名称",
        description="按名称查找模板，例如「旅游规划」；与 template_id 二选一。",
    )


class CreateNoteFromTemplateArgs(BaseModel):
    template_id: uuid.UUID | None = Field(
        default=None,
        title="模板 ID",
        description="模板 UUID，来自 list_templates；与 name 二选一。",
    )
    name: str = Field(
        default="",
        max_length=200,
        title="模板名称",
        description="按名称查找模板，例如「旅游规划」；与 template_id 二选一。",
    )
    title: str = Field(
        default="",
        max_length=300,
        title="笔记标题",
        description="留空时使用模板的默认标题格式（{{date}} 会替换为当天）。",
    )
    folder_id: uuid.UUID | None = Field(
        default=None,
        title="分组",
        description="放到该分组；不传表示知识库根目录。",
    )
    parent_note_id: uuid.UUID | None = Field(
        default=None,
        title="父笔记",
        description="作为该笔记的子笔记；与 folder_id 二选一。",
    )

    @model_validator(mode="after")
    def require_template(self):
        if self.template_id is None and not self.name.strip():
            raise ValueError("请提供 template_id 或 name")
        return self


class ApplyTemplateArgs(BaseModel):
    note_id: uuid.UUID = Field(title="笔记", description="要写入模板的笔记 UUID。")
    template_id: uuid.UUID | None = Field(
        default=None,
        title="模板 ID",
        description="模板 UUID，来自 list_templates；与 name 二选一。",
    )
    name: str = Field(
        default="",
        max_length=200,
        title="模板名称",
        description="按名称查找模板；与 template_id 二选一。",
    )
    mode: Literal["replace", "prepend", "append"] = Field(
        default="replace",
        title="写入方式",
        description="replace 替换正文（会覆盖原内容）；prepend 放到正文前；append 追加到正文后。",
    )

    @model_validator(mode="after")
    def require_template(self):
        if self.template_id is None and not self.name.strip():
            raise ValueError("请提供 template_id 或 name")
        return self


class QueryDatabaseRowsArgs(BaseModel):
    note_id: uuid.UUID = Field(
        title="数据表",
        description="数据表笔记 UUID，可先用 list_databases 获取。",
    )
    limit: int = Field(
        default=50, ge=1, le=200, title="返回条数", description="最多返回多少条，1-200，默认 50。"
    )


class CreateNoteArgs(BaseModel):
    title: str = Field(
        min_length=1, max_length=300, title="标题", description="笔记标题，不能为空。"
    )
    body_md: str = Field(
        default="",
        max_length=MAX_NOTE_BODY,
        title="正文",
        description="Markdown 正文；文档、画布等类型都先以 Markdown 写入。",
    )
    kind: str = Field(
        default="doc",
        max_length=20,
        title="类型",
        description="doc / canvas / sheet / notebook / database，默认 doc。",
    )
    folder_id: uuid.UUID | None = Field(
        default=None, title="分组", description="放入该分组；不传表示根目录。"
    )
    parent_note_id: uuid.UUID | None = Field(
        default=None, title="父笔记", description="作为该笔记的子笔记；不传表示顶层笔记。"
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=30,
        title="标签",
        description="标签名数组；不传表示没有标签。",
    )

    @model_validator(mode="after")
    def check_kind(self):
        if self.kind not in {"doc", "canvas", "sheet", "notebook", "database"}:
            raise ValueError("kind 只支持 doc / canvas / sheet / notebook / database")
        return self


class UpdateNoteArgs(BaseModel):
    note_id: uuid.UUID = Field(
        title="笔记", description="要修改的笔记 UUID，必须来自工具返回结果。"
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        title="新标题",
        description="不传表示不修改标题。",
    )
    body_md: str | None = Field(
        default=None,
        max_length=MAX_NOTE_BODY,
        title="新正文",
        description="完整的 Markdown 正文，会整段替换旧正文；不传表示不修改。",
    )
    tags: list[str] | None = Field(
        default=None,
        max_length=30,
        title="新标签",
        description="完整的标签数组，会整组替换；不传表示不修改。",
    )
    folder_id: uuid.UUID | None = Field(
        default=None,
        title="移动到分组",
        description="传 null 移到根目录；不传表示不修改。",
    )
    parent_note_id: uuid.UUID | None = Field(
        default=None,
        title="父笔记",
        description="改挂到该父笔记；传 null 取消父子关系；不传表示不修改。",
    )

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set & {
            "title",
            "body_md",
            "tags",
            "folder_id",
            "parent_note_id",
        }:
            raise ValueError("至少提供一个要修改的字段")
        return self


class DeleteNoteArgs(BaseModel):
    note_id: uuid.UUID = Field(
        title="笔记", description="要移入回收站的笔记 UUID。"
    )


class CreateFolderArgs(BaseModel):
    name: str = Field(
        min_length=1, max_length=200, title="分组名", description="新分组的名称。"
    )
    parent_id: uuid.UUID | None = Field(
        default=None, title="父分组", description="放在该分组下；不传表示根目录。"
    )


class UpdateFolderArgs(BaseModel):
    folder_id: uuid.UUID = Field(title="分组", description="要修改的分组 UUID。")
    name: str | None = Field(
        default=None, min_length=1, max_length=200, title="新名称", description="不传表示不重命名。"
    )
    parent_id: uuid.UUID | None = Field(
        default=None,
        title="父分组",
        description="传 null 移到根目录；不传表示不修改层级。",
    )
    pinned: bool | None = Field(
        default=None, title="置顶", description="true 置顶，false 取消置顶；不传表示不修改。"
    )

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set & {"name", "parent_id", "pinned"}:
            raise ValueError("至少提供一个要修改的字段")
        return self


class DeleteFolderArgs(BaseModel):
    folder_id: uuid.UUID = Field(
        title="分组", description="要删除的分组 UUID；其中的笔记会移入回收站。"
    )


class CreateDatabaseRowArgs(BaseModel):
    note_id: uuid.UUID = Field(title="数据表", description="数据表笔记 UUID。")
    data: dict = Field(
        default_factory=dict,
        title="字段数据",
        description='字段 id 到值的对象，例如 {"name": "记录一"}；字段 id 来自 list_databases / query_database_rows 的 fields。',
    )


class UpdateDatabaseRowArgs(BaseModel):
    note_id: uuid.UUID = Field(title="数据表", description="数据表笔记 UUID。")
    row_id: uuid.UUID = Field(title="记录", description="要修改的记录 UUID。")
    data: dict = Field(
        default_factory=dict,
        title="字段数据",
        description="要更新的字段 id 到新值的对象，未提供的字段保持不变。",
    )


class DeleteDatabaseRowArgs(BaseModel):
    note_id: uuid.UUID = Field(title="数据表", description="数据表笔记 UUID。")
    row_id: uuid.UUID = Field(title="记录", description="要删除的记录 UUID。")


class ListKnowledgeBasesArgs(BaseModel):
    pass


class ScheduleWeChatPushArgs(BaseModel):
    prompt: str = Field(
        min_length=1,
        max_length=2000,
        title="推送内容",
        description=(
            "定时任务每次要生成的内容。写清楚目标和知识库，"
            "例如「总结 XXX 知识库今天的待办，按优先级列出」。"
        ),
    )
    cron: str = Field(
        default="",
        max_length=120,
        title="Cron 表达式",
        description=(
            "标准 5 段 cron（分 时 日 月 周，周日=0），优先使用。例如每天 09:00 为 0 9 * * *。"
        ),
    )
    schedule: str = Field(
        default="",
        max_length=200,
        title="自然语言计划",
        description=(
            "没有 cron 时填写自然语言计划，例如「每天早上九点」「工作日 08:30」"
            "「每周一 10:00」「每月 1 号 09:00」。"
        ),
    )
    time: str = Field(
        default="",
        max_length=5,
        title="旧版时间",
        description="兼容旧调用：HH:MM，默认按每天执行；新调用请用 cron 或 schedule。",
    )
    kb_names: list[str] = Field(
        default_factory=list,
        title="知识库名称",
        description="目标知识库名称数组，支持跨库汇总；留空时使用 kb_name 或当前知识库。",
    )
    kb_name: str = Field(
        default="",
        max_length=200,
        title="知识库名称",
        description="单个目标知识库名称；可先用 list_knowledge_bases 查询。",
    )


class ListWeChatPushesArgs(BaseModel):
    pass


class CancelWeChatPushArgs(BaseModel):
    schedule_id: str = Field(
        min_length=1, max_length=40, title="任务 ID", description="定时任务 ID。"
    )


@dataclass
class _RegisteredTool:
    definition: ToolDef
    handler: Callable[[AsyncSession, uuid.UUID, Any], Awaitable[dict[str, Any]]]


_REGISTRY: dict[str, _RegisteredTool] = {}


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    # 顶层的模型名对 LLM 没有意义，参数说明都在 properties 里。
    schema.pop("title", None)
    return schema


def register_tool(
    definition: ToolDef,
    handler: Callable[[AsyncSession, uuid.UUID, Any], Awaitable[dict[str, Any]]],
) -> None:
    """注册一个内置工具；重复注册后注册者覆盖先注册者。"""
    if definition.name.startswith("mcp__"):
        raise ValueError("内置工具名不能使用 mcp__ 前缀")
    _REGISTRY[definition.name] = _RegisteredTool(definition, handler)


def _tool(
    name: str,
    label: str,
    description: str,
    args_model: type[BaseModel],
    *,
    read_only: bool,
    destructive: bool = False,
    requires_kb: bool = True,
    summary_template: str = "",
):
    """把一个参数模型 + 处理函数注册成 Agent 工具。"""

    def decorator(handler):
        register_tool(
            ToolDef(
                name=name,
                label=label,
                description=description,
                input_schema=_schema(args_model),
                read_only=read_only,
                destructive=destructive,
                requires_kb=requires_kb,
                args_model=args_model,
                arg_labels=field_labels(args_model),
                summary_template=summary_template,
            ),
            handler,
        )
        return handler

    return decorator


def builtin_tools() -> list[ToolDef]:
    return [item.definition for item in _REGISTRY.values()]


async def load_toolbox() -> Toolbox:
    """构建本轮问答可用的工具集：内置工具 + 已配置的外部 MCP 工具。"""
    tools = builtin_tools()
    try:
        tools = tools + await external_tools()
    except Exception:  # noqa: BLE001 —— 外部服务异常不能影响内置能力
        logger.exception("发现外部 MCP 工具失败，仅使用内置工具")
    return Toolbox(
        tools,
        builtin_executor=call_builtin_tool,
        remote_executor=call_external_tool,
    )


async def call_builtin_tool(
    session: AsyncSession | None,
    kb_id: uuid.UUID | None,
    tool: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    # 通过模块级名字调用，保持测试 monkeypatch execute_tool 的兼容性。
    return await execute_tool(session, kb_id, tool, args)


def _legacy_tool_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for item in _REGISTRY.values():
        definition = item.definition
        properties = definition.input_schema.get("properties") or {}
        args = {
            str(key): str(prop.get("description") or prop.get("title") or "")
            for key, prop in properties.items()
            if isinstance(prop, dict)
        }
        specs.append(
            {
                "tool": definition.name,
                "read_only": definition.read_only,
                "description": definition.description,
                "args": args,
            }
        )
    return specs


def tool_prompt() -> str:
    return Toolbox(builtin_tools()).prompt()


def prepare_tool_call(
    tool: str, args: dict[str, Any], summary: str, *, can_write: bool
) -> tuple[dict[str, Any], str, str]:
    """校验模型给出的调用，返回 (规范化参数, 标签, 展示摘要)。

    仅覆盖内置工具；Agent 循环使用带外部工具的 ``Toolbox.prepare_call``。
    """
    normalized, label, clean_summary, _labels = Toolbox(
        builtin_tools()
    ).prepare_call(tool, args, summary, can_write=can_write)
    return normalized, label, clean_summary


async def _load_note(
    session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID
) -> Note:
    note = (
        await session.execute(
            select(Note)
            .options(selectinload(Note.tags))
            .where(Note.kb_id == kb_id, Note.id == note_id)
        )
    ).scalar_one_or_none()
    if note is None or note.status not in ("active", "archived"):
        raise ToolError("笔记不存在或已在回收站中")
    if note.lock_hash is not None:
        raise ToolError("该笔记已上锁，Agent 不能读取或修改")
    return note


def _note_brief(note: Note, *, snippet: str = "") -> dict[str, Any]:
    # search_notes 返回 NoteSummary（tags 已是字符串），其余工具返回 ORM Note。
    raw_tags = getattr(note, "tags", []) or []
    tags = [tag if isinstance(tag, str) else tag.name for tag in raw_tags]
    data = {
        "id": str(note.id),
        "title": note.title,
        "kind": note.kind,
        "folder_id": str(note.folder_id) if note.folder_id else None,
        "parent_note_id": str(note.parent_note_id) if note.parent_note_id else None,
        "tags": tags,
        "status": note.status,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }
    if snippet:
        data["snippet"] = snippet[:300]
    return data


def _inclusive_range(
    start: datetime | None, end: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """日期型上限（00:00:00）按「含当天」处理，避免漏掉当天的大部分时间。"""
    if end is not None and end.time() == time.min:
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


@_tool(
    "search_notes",
    "搜索笔记",
    "按关键词搜索当前知识库的标题、正文、标签与数据表文本；支持按类型、分组、"
    "创建/更新时间过滤。问「这周 / 最近做了什么」时优先用 updated_from / updated_to "
    "限定时间范围。",
    SearchNotesArgs,
    read_only=True,
)
async def _search(
    session: AsyncSession, kb_id: uuid.UUID, args: SearchNotesArgs
) -> dict:
    created_from, created_to = _inclusive_range(args.created_from, args.created_to)
    updated_from, updated_to = _inclusive_range(args.updated_from, args.updated_to)
    result = await search_notes_route(
        kb_id=kb_id,
        q=args.query,
        folder_id=args.folder_id,
        tag_ids=[],
        kind=args.kind,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        limit=args.limit,
        offset=0,
        session=session,
    )
    items = [_note_brief(item.note, snippet=item.snippet) for item in result.items]
    return {"total": result.total, "items": items}


@_tool(
    "list_notes",
    "列出笔记",
    "按更新时间倒序列出笔记；支持按分组、类型、创建/更新时间过滤。适合不知道关键词、"
    "需要按时间浏览最近改动的场景。",
    ListNotesArgs,
    read_only=True,
)
async def _list_notes(
    session: AsyncSession, kb_id: uuid.UUID, args: ListNotesArgs
) -> dict:
    created_from, created_to = _inclusive_range(args.created_from, args.created_to)
    updated_from, updated_to = _inclusive_range(args.updated_from, args.updated_to)
    stmt = (
        select(Note)
        .options(selectinload(Note.tags))
        .where(
            Note.kb_id == kb_id,
            Note.lock_hash.is_(None),
            Note.status.in_(["active", "archived"]),
        )
        .order_by(Note.updated_at.desc())
        .limit(args.limit)
        .offset(args.offset)
    )
    if args.folder_id is not None:
        stmt = stmt.where(Note.folder_id == args.folder_id)
    if args.kind:
        stmt = stmt.where(Note.kind == args.kind)
    if created_from:
        stmt = stmt.where(Note.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Note.created_at <= created_to)
    if updated_from:
        stmt = stmt.where(Note.updated_at >= updated_from)
    if updated_to:
        stmt = stmt.where(Note.updated_at <= updated_to)
    notes = (await session.execute(stmt)).scalars().all()
    return {"items": [_note_brief(note) for note in notes], "count": len(notes)}


@_tool(
    "get_note",
    "读取笔记",
    "读取一篇笔记的完整正文、标签与所属分组；长文会截断。搜索片段与问题相关但信息"
    "不足时必须调用它读全文，不要只凭片段下结论。",
    GetNoteArgs,
    read_only=True,
)
async def _get_note(
    session: AsyncSession, kb_id: uuid.UUID, args: GetNoteArgs
) -> dict:
    note = await _load_note(session, kb_id, args.note_id)
    body = note.body_md or ""
    truncated = len(body) > MAX_RESULT_NOTE_BODY
    data = _note_brief(note)
    data["body_md"] = body[:MAX_RESULT_NOTE_BODY]
    data["body_truncated"] = truncated
    return data


@_tool(
    "fetch_url",
    "读取网页",
    "抓取用户给出的公开网页，提取标题、站点与正文 Markdown。用于把网页内容整理成笔记；"
    "只读、无需确认。只支持 http/https 公网地址，本机与内网地址会被拒绝；抓取失败会返回"
    "具体原因。返回的 markdown 是网页正文（开头可能附页面自带摘要），可直接作为 "
    "create_note 的 body_md，不要编造或补写网页没有的内容。",
    FetchUrlArgs,
    read_only=True,
    requires_kb=False,
    summary_template="读取网页 {url}",
)
async def _fetch_url(
    session: AsyncSession | None,
    kb_id: uuid.UUID | None,
    args: FetchUrlArgs,
) -> dict:
    try:
        result = await fetch_and_extract(args.url)
    except SSRFError as e:
        raise ToolError(f"该链接指向本机或内网地址，已拒绝读取：{e}") from e
    except LinkFetchError as e:
        raise ToolError(f"网页读取失败：{e}") from e
    if result.fetch_status != "ok" or not result.markdown.strip():
        raise ToolError(f"网页读取失败：{result.error or '未提取到正文'}")
    markdown = result.markdown.strip()
    excerpt = (result.excerpt or "").strip()
    # 正文提取器有时会漏掉页面主区块（例如诗词原文），而页面摘要恰好含有它。
    # 摘要很短、且没有出现在正文里时，作为引用补在开头；已包含则不重复。
    compact_excerpt = "".join(excerpt.split())
    summary_added = (
        bool(compact_excerpt)
        and len(excerpt) <= 300
        and compact_excerpt not in "".join(markdown.split())
    )
    if summary_added:
        markdown = f"> 页面摘要：{excerpt}\n\n{markdown}"
    truncated = len(markdown) > MAX_RESULT_WEB_BODY
    return {
        "ok": True,
        "url": result.url,
        "final_url": result.final_url,
        "title": result.title,
        "site": result.site,
        "excerpt": excerpt,
        "markdown": markdown[:MAX_RESULT_WEB_BODY],
        "markdown_truncated": truncated,
        "summary_added": summary_added,
        "note": (
            "正文过长，已截断；写入笔记时应说明内容不完整。"
            if truncated
            else "已取得网页正文；新建笔记时把它作为 body_md。"
        ),
    }


@_tool(
    "list_folders",
    "列出分组",
    "列出当前知识库的分组树，返回分组 ID 与名称；创建或移动笔记前可用它确认分组。",
    ListFoldersArgs,
    read_only=True,
)
async def _list_folders(
    session: AsyncSession, kb_id: uuid.UUID, _args: ListFoldersArgs
) -> dict:
    folders = (
        (
            await session.execute(
                select(NoteFolder)
                .where(NoteFolder.kb_id == kb_id)
                .order_by(NoteFolder.sort_order, NoteFolder.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(folder.id),
                "name": folder.name,
                "parent_id": str(folder.parent_id) if folder.parent_id else None,
            }
            for folder in folders
        ]
    }


async def _template_rows(
    session: AsyncSession, kb_id: uuid.UUID
) -> list[NoteTemplate]:
    # 内置模板按需补齐，保证 Agent 与「新建笔记 → 模板」看到的是同一批。
    await _ensure_builtin_templates(session, kb_id)
    return (
        (
            await session.execute(
                select(NoteTemplate)
                .where(NoteTemplate.kb_id == kb_id)
                .order_by(
                    NoteTemplate.is_builtin.desc(),
                    NoteTemplate.sort_order,
                    NoteTemplate.name,
                )
            )
        )
        .scalars()
        .all()
    )


def _template_key(value: str) -> str:
    return "".join(str(value or "").split()).lower()


@_tool(
    "list_templates",
    "列出模板",
    "列出当前知识库的笔记模板（名称、说明、默认标题格式与标签），返回模板 ID 和正文预览。"
    "用户说「基于 / 使用 / 套用某个模板」时，先用本工具按名称找到模板，再用 get_template "
    "读取完整正文；模板不是笔记，不要用 search_notes 查找模板。",
    ListTemplatesArgs,
    read_only=True,
)
async def _list_templates(
    session: AsyncSession, kb_id: uuid.UUID, args: ListTemplatesArgs
) -> dict:
    query = _template_key(args.query)
    items: list[dict[str, Any]] = []
    for template in await _template_rows(session, kb_id):
        if query and query not in _template_key(template.name) and query not in _template_key(
            template.description
        ):
            continue
        body = " ".join((template.body_md or "").split())
        items.append(
            {
                "id": str(template.id),
                "name": template.name,
                "description": template.description,
                "title_pattern": template.title_pattern,
                "tags": list(template.tags_json or []),
                "is_builtin": template.is_builtin,
                "body_chars": len(template.body_md or ""),
                "body_preview": body[:180],
            }
        )
    return {
        "items": items,
        "hint": "需要完整正文时调用 get_template（可用模板 ID 或名称）。",
    }


@_tool(
    "get_template",
    "读取模板",
    "读取指定笔记模板的完整 Markdown 正文、默认标题格式与标签。用户要求「基于模板」生成笔记时，"
    "先取得模板结构，再沿用模板的章节、表格与组件生成内容；不要把模板正文当成检索到的资料。",
    GetTemplateArgs,
    read_only=True,
)
async def _get_template(
    session: AsyncSession, kb_id: uuid.UUID, args: GetTemplateArgs
) -> dict:
    rows = await _template_rows(session, kb_id)
    template: NoteTemplate | None = None
    if args.template_id is not None:
        template = next((row for row in rows if row.id == args.template_id), None)
        if template is None:
            raise ToolError("模板不存在，或不属于当前知识库")
    elif args.name.strip():
        key = _template_key(args.name)
        exact = [row for row in rows if _template_key(row.name) == key]
        if not exact:
            partial = [row for row in rows if key in _template_key(row.name)]
            if len(partial) > 1:
                return {
                    "ambiguous": True,
                    "items": [
                        {"id": str(row.id), "name": row.name} for row in partial
                    ],
                    "hint": "有多个名称相近的模板，请用 template_id 指定其中一个。",
                }
            exact = partial
        if not exact:
            names = "、".join(row.name for row in rows[:20]) or "（无）"
            raise ToolError(f"没有找到名为「{args.name}」的模板。可用模板：{names}")
        template = exact[0]
    else:
        raise ToolError("请提供 template_id 或 name")

    body = template.body_md or ""
    truncated = len(body) > MAX_RESULT_NOTE_BODY
    return {
        "id": str(template.id),
        "name": template.name,
        "description": template.description,
        "title_pattern": template.title_pattern,
        "tags": list(template.tags_json or []),
        "is_builtin": template.is_builtin,
        "body_md": body[:MAX_RESULT_NOTE_BODY],
        "body_truncated": truncated,
        "hint": (
            "请沿用模板的章节结构与组件，把用户给出的信息填进去；"
            "模板里的示例内容要替换，不要原样保留。"
        ),
    }


async def _resolve_template(
    session: AsyncSession,
    kb_id: uuid.UUID,
    template_id: uuid.UUID | None,
    name: str,
) -> NoteTemplate:
    rows = await _template_rows(session, kb_id)
    if template_id is not None:
        found = next((row for row in rows if row.id == template_id), None)
        if found is None:
            raise ToolError("模板不存在，或不属于当前知识库")
        return found
    key = _template_key(name)
    exact = [row for row in rows if _template_key(row.name) == key]
    if len(exact) == 1:
        return exact[0]
    partial = [row for row in rows if key and key in _template_key(row.name)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        names = "、".join(row.name for row in partial[:10])
        raise ToolError(f"有多个名称相近的模板：{names}；请提供 template_id")
    available = "、".join(row.name for row in rows[:20]) or "（无）"
    raise ToolError(f"没有找到名为「{name}」的模板。可用模板：{available}")


def _template_note_title(template: NoteTemplate, override: str) -> str:
    title = override.strip()
    if not title:
        title = (template.title_pattern or template.name or "无标题文档").replace(
            "{{date}}", datetime.now().strftime("%Y-%m-%d")
        )
    return (title.strip() or template.name or "无标题文档")[:300]


@_tool(
    "create_note_from_template",
    "按模板新建笔记",
    "按现有模板新建一篇笔记，只套用模板的正文结构与标签，不生成新内容。"
    "用户要求「用某个模板新建笔记 / 套用模板」时使用；模板 ID 或名称来自 "
    "list_templates。写操作需要用户确认。",
    CreateNoteFromTemplateArgs,
    read_only=False,
    summary_template="按模板《{name}》新建笔记",
)
async def _create_note_from_template(
    session: AsyncSession,
    kb_id: uuid.UUID,
    args: CreateNoteFromTemplateArgs,
) -> dict:
    template = await _resolve_template(session, kb_id, args.template_id, args.name)
    note = await create_note_route(
        NoteCreate(
            title=_template_note_title(template, args.title),
            body_md=template.body_md or "",
            kind="doc",
            folder_id=args.folder_id,
            parent_note_id=args.parent_note_id,
            tags=[str(tag) for tag in template.tags_json or []][:30],
        ),
        kb_id=kb_id,
        session=session,
    )
    return {
        "ok": True,
        "note": {"id": str(note.id), "title": note.title, "kind": note.kind},
        "template": {"id": str(template.id), "name": template.name},
    }


@_tool(
    "apply_template",
    "套用模板到笔记",
    "把模板正文写入一篇现有笔记：replace 替换正文（会覆盖原内容）、prepend 放到前面、"
    "append 追加到后面。目标笔记上锁或在回收站时不可写；写操作需要用户确认，"
    "系统会在修改前保留笔记历史版本。",
    ApplyTemplateArgs,
    read_only=False,
    summary_template="套用模板《{name}》",
)
async def _apply_template(
    session: AsyncSession,
    kb_id: uuid.UUID,
    args: ApplyTemplateArgs,
) -> dict:
    note = await _load_note(session, kb_id, args.note_id)
    template = await _resolve_template(session, kb_id, args.template_id, args.name)
    old_body = note.body_md or ""
    template_body = template.body_md or ""
    if args.mode == "prepend":
        body = template_body + (f"\n\n{old_body}" if old_body else "")
    elif args.mode == "append":
        body = old_body + (f"\n\n{template_body}" if template_body else "")
    else:
        body = template_body
    updated = await update_note_route(
        note_id=note.id,
        kb_id=kb_id,
        data=NoteUpdate(body_md=body),
        x_note_token=None,
        session=session,
    )
    return {
        "ok": True,
        "note": {"id": str(updated.id), "title": updated.title, "kind": updated.kind},
        "mode": args.mode,
        "template": {"id": str(template.id), "name": template.name},
        "previous_chars": len(old_body),
    }


@_tool(
    "list_databases",
    "列出数据表",
    "列出当前知识库的数据表及其字段结构；返回的字段 id 用于读写数据表记录。",
    ListDatabasesArgs,
    read_only=True,
)
async def _list_databases(
    session: AsyncSession, kb_id: uuid.UUID, _args: ListDatabasesArgs
) -> dict:
    notes = (
        (
            await session.execute(
                select(Note)
                .where(
                    Note.kb_id == kb_id,
                    Note.kind == "database",
                    Note.lock_hash.is_(None),
                    Note.status.in_(["active", "archived"]),
                )
                .order_by(Note.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items = []
    for note in notes:
        coll = await ensure_collection(session, note)
        fields = [
            {"id": field.get("id"), "name": field.get("name"), "type": field.get("type")}
            for field in ((coll.schema_json or {}).get("fields") or [])
        ]
        items.append({"id": str(note.id), "title": note.title, "fields": fields})
    return {"items": items}


async def _database_note(
    session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID
) -> Note:
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id or note.kind != "database":
        raise ToolError("数据表不存在")
    if note.status not in ("active", "archived"):
        raise ToolError("数据表已在回收站中")
    if note.lock_hash is not None:
        raise ToolError("该数据表已上锁，Agent 不能读取或修改")
    return note


@_tool(
    "query_database_rows",
    "查询数据表记录",
    "读取数据表的记录与字段定义；记录里的 note_id 可继续用 get_note 读取关联笔记。",
    QueryDatabaseRowsArgs,
    read_only=True,
)
async def _query_rows(
    session: AsyncSession, kb_id: uuid.UUID, args: QueryDatabaseRowsArgs
) -> dict:
    note = await _database_note(session, kb_id, args.note_id)
    coll = await ensure_collection(session, note)
    rows = await list_rows_route(note_id=args.note_id, kb_id=kb_id, session=session)
    fields = [
        {"id": field.get("id"), "name": field.get("name"), "type": field.get("type")}
        for field in ((coll.schema_json or {}).get("fields") or [])
    ]
    return {
        "database": {"id": str(note.id), "title": note.title, "fields": fields},
        "items": [
            {
                "id": str(row.id),
                "note_id": str(row.note_id) if row.note_id else None,
                "data": row.data,
                "sort_order": row.sort_order,
            }
            for row in rows[: args.limit]
        ],
        "count": len(rows),
    }


@_tool(
    "create_note",
    "新建笔记",
    "新建笔记；默认文档。写操作需要用户确认，确认前不要声称已创建。",
    CreateNoteArgs,
    read_only=False,
    summary_template="新建笔记《{title}》",
)
async def _create_note(
    session: AsyncSession, kb_id: uuid.UUID, args: CreateNoteArgs
) -> dict:
    note = await create_note_route(
        NoteCreate(
            title=args.title,
            body_md=args.body_md,
            kind=args.kind,  # type: ignore[arg-type]
            folder_id=args.folder_id,
            parent_note_id=args.parent_note_id,
            tags=args.tags,
        ),
        kb_id=kb_id,
        session=session,
    )
    return {"ok": True, "note": {"id": str(note.id), "title": note.title, "kind": note.kind}}


@_tool(
    "update_note",
    "修改笔记",
    "修改笔记标题、正文、标签、所属分组或父笔记。写操作需要用户确认；body_md 是整段"
    "替换，修改前应先用 get_note 读取原文。",
    UpdateNoteArgs,
    read_only=False,
    summary_template="修改笔记 {note_id:.8}",
)
async def _update_note(
    session: AsyncSession, kb_id: uuid.UUID, args: UpdateNoteArgs
) -> dict:
    note = await _load_note(session, kb_id, args.note_id)
    payload: dict[str, Any] = {}
    for field in ("title", "body_md", "tags", "folder_id", "parent_note_id"):
        if field in args.model_fields_set:
            payload[field] = getattr(args, field)
    updated = await update_note_route(
        note_id=note.id,
        kb_id=kb_id,
        data=NoteUpdate(**payload),
        x_note_token=None,
        session=session,
    )
    return {
        "ok": True,
        "note": {"id": str(updated.id), "title": updated.title, "kind": updated.kind},
    }


@_tool(
    "delete_note",
    "移入回收站",
    "把笔记移入回收站（可恢复），不执行永久删除；写操作需要用户确认。",
    DeleteNoteArgs,
    read_only=False,
    destructive=True,
    summary_template="将笔记 {note_id:.8} 移入回收站",
)
async def _delete_note(
    session: AsyncSession, kb_id: uuid.UUID, args: DeleteNoteArgs
) -> dict:
    note = await _load_note(session, kb_id, args.note_id)
    await delete_note_route(note_id=note.id, kb_id=kb_id, session=session)
    return {"ok": True, "note_id": str(note.id), "status": "trash"}


@_tool(
    "create_folder",
    "新建分组",
    "新建分组；写操作需要用户确认。",
    CreateFolderArgs,
    read_only=False,
    summary_template="新建分组「{name}」",
)
async def _create_folder(
    session: AsyncSession, kb_id: uuid.UUID, args: CreateFolderArgs
) -> dict:
    folder = await create_folder_route(
        NoteFolderCreate(name=args.name, parent_id=args.parent_id),
        kb_id=kb_id,
        session=session,
    )
    return {"ok": True, "folder": {"id": str(folder.id), "name": folder.name}}


@_tool(
    "update_folder",
    "修改分组",
    "重命名、移动或置顶分组；parent_id 传 null 表示移到根目录。写操作需要用户确认。",
    UpdateFolderArgs,
    read_only=False,
    summary_template="修改分组 {folder_id:.8}",
)
async def _update_folder(
    session: AsyncSession, kb_id: uuid.UUID, args: UpdateFolderArgs
) -> dict:
    payload: dict[str, Any] = {}
    for field in ("name", "parent_id", "pinned"):
        if field in args.model_fields_set:
            payload[field] = getattr(args, field)
    folder = await update_folder_route(
        folder_id=args.folder_id,
        kb_id=kb_id,
        data=NoteFolderUpdate(**payload),
        session=session,
    )
    return {
        "ok": True,
        "folder": {
            "id": str(folder.id),
            "name": folder.name,
            "parent_id": str(folder.parent_id) if folder.parent_id else None,
            "pinned": folder.pinned,
        },
    }


@_tool(
    "delete_folder",
    "删除分组",
    "删除分组及其子分组，其中的笔记会一并移入回收站（可恢复）；写操作需要用户确认。",
    DeleteFolderArgs,
    read_only=False,
    destructive=True,
    summary_template="删除分组 {folder_id:.8}（笔记移入回收站）",
)
async def _delete_folder(
    session: AsyncSession, kb_id: uuid.UUID, args: DeleteFolderArgs
) -> dict:
    await delete_folder_route(folder_id=args.folder_id, kb_id=kb_id, session=session)
    return {"ok": True, "folder_id": str(args.folder_id), "notes": "trash"}


@_tool(
    "create_database_row",
    "新增数据表记录",
    "在数据表中新增一条记录；data 的键是字段 id。写操作需要用户确认。",
    CreateDatabaseRowArgs,
    read_only=False,
    summary_template="在数据表 {note_id:.8} 新增记录",
)
async def _create_row(
    session: AsyncSession, kb_id: uuid.UUID, args: CreateDatabaseRowArgs
) -> dict:
    note = await _database_note(session, kb_id, args.note_id)
    row = await create_row_route(
        note_id=note.id,
        kb_id=kb_id,
        data=RowCreate(data=args.data),
        session=session,
    )
    return {"ok": True, "row": {"id": str(row.id), "data": row.data}}


@_tool(
    "update_database_row",
    "修改数据表记录",
    "修改数据表记录的部分字段，未提供的字段保持不变；写操作需要用户确认。",
    UpdateDatabaseRowArgs,
    read_only=False,
    summary_template="修改数据表 {note_id:.8} 的记录 {row_id:.8}",
)
async def _update_row(
    session: AsyncSession, kb_id: uuid.UUID, args: UpdateDatabaseRowArgs
) -> dict:
    note = await _database_note(session, kb_id, args.note_id)
    row = await update_row_route(
        note_id=note.id,
        row_id=args.row_id,
        kb_id=kb_id,
        data=RowUpdate(data=args.data),
        session=session,
    )
    return {"ok": True, "row": {"id": str(row.id), "data": row.data}}


@_tool(
    "delete_database_row",
    "删除数据表记录",
    "删除数据表中的一条记录；已生成的笔记会保留。写操作需要用户确认。",
    DeleteDatabaseRowArgs,
    read_only=False,
    destructive=True,
    summary_template="删除数据表 {note_id:.8} 的记录 {row_id:.8}",
)
async def _delete_row(
    session: AsyncSession, kb_id: uuid.UUID, args: DeleteDatabaseRowArgs
) -> dict:
    note = await _database_note(session, kb_id, args.note_id)
    await delete_row_route(
        note_id=note.id, row_id=args.row_id, kb_id=kb_id, session=session
    )
    return {"ok": True, "row_id": str(args.row_id)}


async def execute_tool(
    session: AsyncSession | None,
    kb_id: uuid.UUID | None,
    tool: str,
    args: dict[str, Any],
) -> dict:
    """执行一个内置工具；只读与已获批准的写操作都走这里。"""
    registered = _REGISTRY.get(tool)
    if registered is None:
        raise ToolError(f"未知工具：{tool}")
    definition = registered.definition
    # 联网读取等工具不依赖知识库；全局问答（没有 kb_id）也应可用。
    if definition.requires_kb:
        if session is None:
            raise ToolError("没有可用的数据库会话，无法执行工具")
        if kb_id is None:
            raise ToolError("未确定当前知识库，无法执行工具")
    try:
        model = (
            definition.args_model.model_validate(args or {})
            if definition.args_model is not None
            else args
        )
    except ValidationError as e:
        first = e.errors()[0] if e.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", ()))
        message = first.get("msg", "参数不正确")
        raise ToolError(f"{tool} 参数错误：{field} {message}".strip()) from e
    try:
        return await registered.handler(session, kb_id, model)
    except ToolError:
        raise
    except HTTPException as e:
        if session is not None:
            await session.rollback()
        raise ToolError(str(e.detail)) from e
    except Exception as e:  # noqa: BLE001 —— 工具失败要反馈给模型而不是中断问答
        if session is not None:
            await session.rollback()
        logger.exception("Agent 工具执行失败：%s", tool)
        raise ToolError(f"工具执行失败：{e}") from e


@_tool(
    "list_knowledge_bases",
    "列出知识库",
    "列出当前实例的知识库名称与 ID；跨知识库创建笔记或定时推送前，先用它确认目标知识库。",
    ListKnowledgeBasesArgs,
    read_only=True,
    requires_kb=False,
)
async def _list_knowledge_bases(session: AsyncSession, _kb_id, _args) -> dict:
    from app.db.models import KnowledgeBase

    rows = (
        (
            await session.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.deleted_at.is_(None))
                .order_by(KnowledgeBase.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {"id": str(kb.id), "name": kb.name, "description": kb.description}
            for kb in rows
        ]
    }


@_tool(
    "schedule_wechat_push",
    "创建 ClawBot 定时推送",
    "仅 ClawBot 渠道可用：创建定时推送到当前对话的任务。用户说「每天早上九点给我 "
    "XXX 知识库的待办」时使用；可用 5 段 cron 或自然语言计划，prompt 写清楚每次要生成的内容。",
    ScheduleWeChatPushArgs,
    read_only=True,
    requires_kb=False,
    summary_template="创建定时推送",
)
async def _schedule_wechat_push(
    session: AsyncSession, kb_id: uuid.UUID | None, args: ScheduleWeChatPushArgs
) -> dict:
    from app.db.models import KnowledgeBase
    from app.services import cron_schedule, schedule_parser, wechat_clawbot
    from app.services.channel_context import current_wechat_sender

    sender = current_wechat_sender.get()
    if not sender:
        raise ToolError("定时推送仅支持 ClawBot 渠道；Web 端请在「设置 → ClawBot」创建")

    names = [item.strip() for item in args.kb_names if item.strip()]
    if args.kb_name.strip() and args.kb_name.strip() not in names:
        names.append(args.kb_name.strip())
    targets: list[KnowledgeBase] = []
    if names:
        for name in names[:5]:
            rows = (
                (
                    await session.execute(
                        select(KnowledgeBase).where(
                            KnowledgeBase.deleted_at.is_(None),
                            KnowledgeBase.name.ilike(f"%{name}%"),
                        )
                    )
                )
                .scalars()
                .all()
            )
            target = next((kb for kb in rows if kb.name == name), None) or (
                rows[0] if len(rows) == 1 else None
            )
            if target is None:
                available = ", ".join(kb.name for kb in rows[:10]) or "无匹配"
                raise ToolError(f"没有唯一匹配的知识库「{name}」；候选：{available}")
            targets.append(target)
    elif kb_id is not None:
        target = await session.get(KnowledgeBase, kb_id)
        if target is not None and target.deleted_at is None:
            targets.append(target)
    if not targets:
        raise ToolError("请指定至少一个知识库名称；可先用 list_knowledge_bases 查询")

    try:
        if args.cron.strip():
            cron = cron_schedule.validate_cron(args.cron.strip())
        elif args.schedule.strip():
            cron, _description = await schedule_parser.parse_schedule(
                args.schedule.strip(), session=session
            )
        elif args.time.strip():
            cron = cron_schedule.from_legacy_time(args.time.strip())
        else:
            raise ToolError("请提供 cron、自然语言计划或 HH:MM 时间")
    except (cron_schedule.CronError, schedule_parser.ScheduleParseError) as exc:
        raise ToolError(str(exc)) from exc

    try:
        item = await wechat_clawbot.get_channel().schedule_push(
            sender,
            [str(target.id) for target in targets],
            args.prompt,
            cron,
        )
    except (ValueError, cron_schedule.CronError) as exc:
        raise ToolError(str(exc)) from exc
    return {
        "ok": True,
        "schedule": {
            "id": item["id"],
            "cron": item["cron"],
            "description": cron_schedule.describe(item["cron"]),
            "kb_ids": [str(target.id) for target in targets],
            "kb_names": [target.name for target in targets],
            "prompt": item["prompt"],
        },
    }


@_tool(
    "list_wechat_pushes",
    "列出 ClawBot 定时推送",
    "仅 ClawBot 渠道可用：列出当前对话的定时推送任务。",
    ListWeChatPushesArgs,
    read_only=True,
    requires_kb=False,
)
async def _list_wechat_pushes(
    session: AsyncSession, _kb_id, _args: ListWeChatPushesArgs
) -> dict:
    from app.services import cron_schedule, wechat_clawbot
    from app.services.channel_context import current_wechat_sender

    sender = current_wechat_sender.get()
    if not sender:
        raise ToolError("仅 ClawBot 渠道可用")
    items = []
    for item in await wechat_clawbot.get_channel().list_schedules():
        if item.get("sender") != sender:
            continue
        try:
            cron = cron_schedule.schedule_cron(item)
            description = cron_schedule.describe(cron)
        except cron_schedule.CronError:
            cron = str(item.get("cron") or "")
            description = cron
        items.append(
            {
                "id": item.get("id"),
                "cron": cron,
                "description": description,
                "prompt": item.get("prompt"),
                "kb_ids": item.get("kb_ids") or [],
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return {"items": items}


@_tool(
    "cancel_wechat_push",
    "取消 ClawBot 定时推送",
    "仅 ClawBot 渠道可用：按任务 ID 取消当前对话的定时推送。",
    CancelWeChatPushArgs,
    read_only=True,
    requires_kb=False,
    summary_template="取消定时推送 {schedule_id}",
)
async def _cancel_wechat_push(
    session: AsyncSession, _kb_id, args: CancelWeChatPushArgs
) -> dict:
    from app.services import wechat_clawbot
    from app.services.channel_context import current_wechat_sender

    sender = current_wechat_sender.get()
    if not sender:
        raise ToolError("仅微信渠道可用")
    channel = wechat_clawbot.get_channel()
    items = await channel.list_schedules()
    target = next(
        (
            item
            for item in items
            if item.get("id") == args.schedule_id and item.get("sender") == sender
        ),
        None,
    )
    if target is None:
        raise ToolError("定时任务不存在或不属于当前微信")
    await channel.delete_schedule(args.schedule_id)
    return {"ok": True, "schedule_id": args.schedule_id}


# 兼容旧调用方 / 测试：这些值从注册表派生，不再手工维护枚举。
TOOL_SPECS: list[dict[str, Any]] = _legacy_tool_specs()
TOOL_LABELS: dict[str, str] = {
    item.definition.name: item.definition.label for item in _REGISTRY.values()
}
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    item.definition.name for item in _REGISTRY.values() if item.definition.read_only
)


__all__ = [
    "READ_ONLY_TOOLS",
    "TOOL_LABELS",
    "TOOL_SPECS",
    "ToolError",
    "builtin_tools",
    "call_builtin_tool",
    "execute_tool",
    "load_toolbox",
    "prepare_tool_call",
    "register_tool",
    "tool_prompt",
]
