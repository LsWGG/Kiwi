"""编辑器内置扩展组件：清单下发、启停与内置包导出。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system_settings import SYSTEM_SETTINGS_ID, SystemSettings
from app.db.session import get_session
from app.schemas.editor_extensions import (
    EditorExtensionsOut,
    EditorExtensionsUpdate,
)
from app.services import editor_extensions, system_settings

router = APIRouter(prefix="/api/editor/extensions", tags=["editor-extensions"])
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _write_builtin_archive(
    archive: zipfile.ZipFile, key: str, prefix: str = ""
) -> None:
    package = editor_extensions.builtin_package(key)
    archive.writestr(
        f"{prefix}plugin.json",
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
    )
    archive.writestr(
        f"{prefix}preview.json",
        json.dumps(
            {
                "block": key,
                "props": package["blocks"][0].get("default_props", {}),
                "node": package["runtime"].get("node", ""),
                "markdown": editor_extensions.BUILTIN_PREVIEW_MARKDOWN.get(key, ""),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    archive.writestr(f"{prefix}README.md", editor_extensions.builtin_readme(key))
    for source in package["runtime"].get("source_files", []):
        relative = PurePosixPath(
            "frontend/src/components/editor/extensions", str(source)
        )
        path = PROJECT_ROOT / relative
        if path.is_file():
            try:
                archive.writestr(
                    f"{prefix}source/{relative.name}",
                    path.read_text(encoding="utf-8-sig"),
                )
            except OSError:
                continue


@router.get("/export", response_model=None)
async def export_all_builtin_extensions():
    """导出全部内置组件包，按组件分目录。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for key in editor_extensions.KEYS:
            _write_builtin_archive(archive, key, prefix=f"kiwi-builtin-{key}/")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="kiwi-builtin-extensions.zip"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("/{key}/export", response_model=None)
async def export_builtin_extension(key: str):
    """导出单个内置组件包。"""
    if key not in editor_extensions.KEYS:
        raise HTTPException(404, "内置扩展组件不存在")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        _write_builtin_archive(archive, key)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="kiwi-builtin-{key}.zip"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("", response_model=EditorExtensionsOut)
async def list_editor_extensions(session: AsyncSession = Depends(get_session)):
    return editor_extensions.payload(await system_settings.get_row(session))


@router.put("", response_model=EditorExtensionsOut)
async def save_editor_extensions(
    data: EditorExtensionsUpdate, session: AsyncSession = Depends(get_session)
):
    try:
        disabled = editor_extensions.normalize_disabled(data.disabled)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    row = await system_settings.get_row(session)
    if row is None:
        row = SystemSettings(id=SYSTEM_SETTINGS_ID)
        session.add(row)
    row.editor_disabled_extensions = disabled
    await session.commit()
    await session.refresh(row)
    return editor_extensions.payload(row)
