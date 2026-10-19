"""Notebook 路由：单元格执行、内核状态、`.ipynb` 导入导出。"""

from __future__ import annotations

import asyncio
import json
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeBase, Note, NoteFolder
from app.db.session import get_session
from app.schemas.note import NoteOut
from app.services.notebook_format import doc_from_ipynb, doc_to_ipynb
from app.services.notebook_kernel import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_CODE_CHARS,
    MAX_TIMEOUT_SECONDS,
    kernel_manager,
)
from app.services.sandbox import SandboxUnavailable

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])

MAX_IPYNB_BYTES = 20 * 1024 * 1024


class ExecuteIn(BaseModel):
    cell_id: str = Field(default="", max_length=100)
    code: str = Field(default="", max_length=MAX_CODE_CHARS)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, ge=1, le=MAX_TIMEOUT_SECONDS)


class ExecuteOut(BaseModel):
    ok: bool
    cell_id: str = ""
    outputs: list[dict] = Field(default_factory=list)
    execution_count: int = 0
    duration_ms: int = 0
    timed_out: bool = False
    kernel_restarted: bool = False
    busy: bool = False
    error: str | None = None


class KernelStatusOut(BaseModel):
    running: bool
    execution_count: int = 0
    python_version: str = ""
    workdir: str = ""
    busy: bool = False
    idle_seconds: int = 0
    sandbox: dict = Field(default_factory=dict)


async def _get_notebook(session: AsyncSession, kb_id: uuid.UUID, note_id: uuid.UUID) -> Note:
    note = await session.get(Note, note_id)
    if note is None or note.kb_id != kb_id:
        raise HTTPException(404, "笔记不存在")
    if note.kind != "notebook":
        raise HTTPException(400, "该笔记不是 Notebook 类型")
    return note


async def _validate_folder(
    session: AsyncSession, kb_id: uuid.UUID, folder_id: uuid.UUID | None
) -> None:
    if folder_id is None:
        return
    folder = await session.get(NoteFolder, folder_id)
    if folder is None or folder.kb_id != kb_id:
        raise HTTPException(404, "分组不存在")


@router.post("/{note_id}/execute", response_model=ExecuteOut)
async def execute_cell(
    note_id: uuid.UUID,
    payload: ExecuteIn,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_notebook(session, kb_id, note_id)
    # 内核执行是阻塞的（select 等待子进程），放到线程池避免卡住事件循环。
    result = await asyncio.to_thread(
        kernel_manager.execute,
        str(kb_id),
        str(note_id),
        payload.code,
        timeout=payload.timeout_seconds,
    )
    return ExecuteOut(
        ok=result.ok,
        cell_id=payload.cell_id,
        outputs=result.outputs,
        execution_count=result.execution_count,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        kernel_restarted=result.kernel_restarted,
        busy=result.busy,
        error=result.error,
    )


@router.get("/{note_id}/status", response_model=KernelStatusOut)
async def kernel_status(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_notebook(session, kb_id, note_id)
    data = await asyncio.to_thread(
        kernel_manager.status, str(kb_id), str(note_id)
    )
    return KernelStatusOut(**data)


@router.post("/{note_id}/restart", response_model=KernelStatusOut)
async def restart_kernel(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_notebook(session, kb_id, note_id)
    try:
        data = await asyncio.to_thread(
            kernel_manager.restart, str(kb_id), str(note_id)
        )
        return KernelStatusOut(**data)
    except SandboxUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/{note_id}/export")
async def export_ipynb(
    note_id: uuid.UUID,
    kb_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    note = await _get_notebook(session, kb_id, note_id)
    doc = (note.props_json or {}).get("notebook_doc") or {}
    payload = doc_to_ipynb(doc if isinstance(doc, dict) else {}, title=note.title)
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    filename = f"{note.title or 'notebook'}.ipynb"
    return Response(
        content=body,
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": (
                "attachment; filename=\"notebook.ipynb\"; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/import", response_model=NoteOut, status_code=201)
async def import_ipynb(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    folder_id: uuid.UUID | None = Form(None),
    parent_note_id: uuid.UUID | None = Form(None),
    title: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await _validate_folder(session, kb_id, folder_id)
    if parent_note_id is not None:
        parent = await session.get(Note, parent_note_id)
        if parent is None or parent.kb_id != kb_id or parent.status != "active":
            raise HTTPException(400, "父笔记不存在或不在工作区")
        folder_id = parent.folder_id

    filename = file.filename or "notebook.ipynb"
    if not filename.lower().endswith(".ipynb"):
        raise HTTPException(415, "仅支持 .ipynb 文件")
    content = await file.read()
    if not content:
        raise HTTPException(400, "空文件")
    if len(content) > MAX_IPYNB_BYTES:
        raise HTTPException(413, "Notebook 文件超过 20MB")
    try:
        raw = json.loads(content.decode("utf-8-sig"))
        doc = doc_from_ipynb(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Notebook 不是有效的 JSON 文件") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    name = (title or "").strip() or filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "未命名 Notebook"
    sort_order = (
        await session.execute(
            select(func.coalesce(func.max(Note.sort_order), -1) + 1).where(
                Note.kb_id == kb_id,
                Note.folder_id == folder_id,
                Note.parent_note_id == parent_note_id
                if parent_note_id is not None
                else Note.parent_note_id.is_(None),
            )
        )
    ).scalar_one()
    note = Note(
        kb_id=kb_id,
        title=name[:300],
        body_md="",
        folder_id=folder_id,
        parent_note_id=parent_note_id,
        kind="notebook",
        status="active",
        view_mode="edit",
        sort_order=int(sort_order),
        props_json={
            "notebook_doc": doc,
            "notebook_import": {"filename": filename, "cell_count": len(doc.get("cells") or [])},
        },
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return NoteOut.model_validate(note, from_attributes=True)
