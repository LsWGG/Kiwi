"""组件插件注册管理：zip 导入导出、启停与资源下发。

插件仅支持组件插件，zip 包结构：

    plugin.json        # manifest（kind=component）
    index.js           # 单文件 ESM，导出 setup(host)
    style.css          # 可选
    README.md          # 可选

服务端只存储和原样下发脚本，不在服务端执行；脚本由浏览器在用户明确安装并启用后加载。
历史模板插件记录保留在库中，但不再出现在列表、区块清单与导入入口。
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plugin
from app.db.session import get_session
from app.schemas.plugin import (
    MANIFEST_VERSION,
    MAX_MANIFEST_CHARS,
    PluginBlockOut,
    PluginInspectionOut,
    PluginManifestIn,
    PluginOut,
    PluginUpdate,
)
from app.services import plugin_registry

logger = logging.getLogger("kiwi.plugins")

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_FILE_BYTES = 1024 * 1024
MAX_SCRIPT_BYTES = 2 * 1024 * 1024
MAX_STYLE_BYTES = 512 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEV_KIT_FILES = (
    "docs/PLUGIN_SPEC.md",
    "docs/examples/plugins/README.md",
    "docs/examples/plugins/counter/plugin.json",
    "docs/examples/plugins/counter/index.js",
    "docs/examples/plugins/counter/style.css",
    "docs/examples/plugins/counter/README.md",
    "docs/examples/plugins/pomodoro/plugin.json",
    "docs/examples/plugins/pomodoro/index.js",
    "docs/examples/plugins/pomodoro/style.css",
    "docs/examples/plugins/pomodoro/README.md",
    "docs/examples/plugins/countdown/plugin.json",
    "docs/examples/plugins/countdown/index.js",
    "docs/examples/plugins/countdown/style.css",
    "docs/examples/plugins/countdown/README.md",
    ".claude/skills/kiwi-plugin/SKILL.md",
)


@dataclass
class PluginPackage:
    """解析后的组件插件包：manifest 与已读取的入口脚本 / 样式。"""

    manifest: PluginManifestIn
    entry: str = ""
    script: str = ""
    style_path: str = ""
    style: str = ""


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = str(first.get("msg") or "manifest 校验失败")
    return f"{loc}：{msg}" if loc else msg


async def _get_plugin(session: AsyncSession, plugin_id: uuid.UUID) -> Plugin:
    plugin = await session.get(Plugin, plugin_id)
    if plugin is None:
        raise HTTPException(404, "插件不存在")
    return plugin


def _parse_manifest_bytes(raw: bytes) -> PluginManifestIn:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"manifest 不是合法的 JSON：{exc}") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "manifest 必须是 JSON 对象")
    if payload.get("kind", "component") != "component":
        raise HTTPException(
            400,
            "插件仅支持组件插件：请将 kind 设为 component，并在 zip 中提供入口脚本",
        )
    try:
        return PluginManifestIn.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(400, _validation_message(exc)) from None


def _manifest_info(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidates = [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and info.filename.lower().split("/")[-1] in ("plugin.json", "manifest.json")
    ]
    if not candidates:
        raise HTTPException(400, "压缩包内缺少 plugin.json / manifest.json")
    if len(candidates) > 1:
        raise HTTPException(400, "压缩包内存在多个 manifest，无法确定使用哪一个")
    info = candidates[0]
    if info.file_size > MAX_MANIFEST_FILE_BYTES:
        raise HTTPException(400, "manifest 文件过大")
    return info


def _zip_member(
    archive: zipfile.ZipFile,
    base_dir: PurePosixPath,
    relative: str,
    limit: int,
    label: str,
) -> zipfile.ZipInfo:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(400, f"{label}路径不能包含上级目录")
    name = str(base_dir / path) if str(base_dir) not in ("", ".") else str(path)
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise HTTPException(404, f"压缩包内缺少{label}：{relative}") from None
    if info.is_dir():
        raise HTTPException(400, f"{label}不能是目录：{relative}")
    if info.file_size > limit:
        raise HTTPException(413, f"{label}过大（上限 {limit // 1024}KB）")
    return info


def _read_zip_text(
    archive: zipfile.ZipFile,
    base_dir: PurePosixPath,
    relative: str,
    limit: int,
    label: str,
    *,
    optional: bool = False,
) -> str:
    try:
        info = _zip_member(archive, base_dir, relative, limit, label)
    except HTTPException as exc:
        if optional and exc.status_code == 404:
            return ""
        raise
    try:
        raw = archive.read(info)
    except (RuntimeError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, f"无法读取{label}：{exc}") from None
    if len(raw) > limit:
        raise HTTPException(413, f"{label}过大（上限 {limit // 1024}KB）")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, f"{label}必须是 UTF-8 文本") from None


def _parse_package(raw: bytes, filename: str) -> PluginPackage:
    looks_zip = filename.lower().endswith(".zip") or raw[:2] == b"PK"
    if not looks_zip:
        raise HTTPException(
            400,
            "组件插件必须打包为 zip，并在包内提供入口脚本（如 index.js）",
        )

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "无法识别压缩包格式") from None
    with archive:
        manifest_info = _manifest_info(archive)
        if manifest_info.file_size > MAX_MANIFEST_FILE_BYTES:
            raise HTTPException(400, "manifest 文件过大")
        manifest = _parse_manifest_bytes(archive.read(manifest_info))

        base_dir = PurePosixPath(manifest_info.filename).parent
        entry = manifest.entry or "index.js"
        script = _read_zip_text(archive, base_dir, entry, MAX_SCRIPT_BYTES, "入口脚本")
        if not script.strip():
            raise HTTPException(400, "组件插件的入口脚本不能为空")

        style_path = manifest.style
        style = ""
        if style_path:
            style = _read_zip_text(archive, base_dir, style_path, MAX_STYLE_BYTES, "样式文件")
        else:
            style = _read_zip_text(
                archive,
                base_dir,
                "style.css",
                MAX_STYLE_BYTES,
                "样式文件",
                optional=True,
            )
            if style:
                style_path = "style.css"

    return PluginPackage(
        manifest=manifest,
        entry=entry,
        script=script,
        style_path=style_path,
        style=style,
    )


def _package_manifest(package: PluginPackage) -> PluginManifestIn:
    """把解析时补全的 entry / style 写回规范化 manifest。"""
    return package.manifest.model_copy(update={"entry": package.entry, "style": package.style_path})


async def _read_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_IMPORT_BYTES:
            raise HTTPException(413, "插件包不能超过 5MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _inspection(package: PluginPackage) -> PluginInspectionOut:
    manifest = package.manifest
    return PluginInspectionOut(
        kind=manifest.kind,
        key=manifest.key,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        entry=package.entry,
        style=package.style_path,
        has_script=bool(package.script),
        has_style=bool(package.style),
        block_count=len(manifest.blocks),
        blocks=[block.label for block in manifest.blocks],
    )


def _export_manifest(plugin: Plugin) -> dict:
    manifest = dict(plugin.manifest or {})
    manifest.update(
        {
            "manifest_version": MANIFEST_VERSION,
            "key": plugin.key,
            "name": plugin.name,
            "version": plugin.version,
            "description": plugin.description,
            "author": plugin.author,
            "icon": plugin.icon,
            "homepage": plugin.homepage,
            "kind": plugin.kind,
            "blocks": plugin.blocks,
        }
    )
    manifest["entry"] = plugin.entry or "index.js"
    manifest["style"] = manifest.get("style") or ("style.css" if plugin.style else "")
    return manifest


def _plugin_readme(plugin: Plugin) -> str:
    lines = [
        f"# {plugin.name}",
        "",
        plugin.description or "由 Kiwi 导出的插件包。",
        "",
        f"- key: `{plugin.key}`",
        f"- version: `{plugin.version}`",
        f"- kind: `{plugin.kind}`",
        "",
    ]
    lines += [
        "## 安装",
        "",
        "在 Kiwi「设置 → 插件与区块 → 导入插件」中选择本 zip。",
        "",
        "组件插件包含可执行 JavaScript，只应从可信来源安装。",
        "",
        "## 开发",
        "",
        "入口脚本导出 `setup(host)`，返回 `{ blocks: { <type>: { component } } }`。",
        "完整规范见 Kiwi 仓库 `docs/PLUGIN_SPEC.md`，或在设置页下载开发套件。",
        "",
    ]
    return "\n".join(lines)


def _export_zip(plugin: Plugin) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = _export_manifest(plugin)
        archive.writestr(
            "plugin.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr("README.md", _plugin_readme(plugin))
        if plugin.script:
            archive.writestr(plugin.entry or "index.js", plugin.script)
            if plugin.style:
                style_path = str(manifest.get("style") or "style.css")
                archive.writestr(style_path, plugin.style)
    return buffer.getvalue()


@router.get("", response_model=list[PluginOut])
async def list_plugins(session: AsyncSession = Depends(get_session)):
    """已安装的组件插件；历史模板插件不再展示。"""
    plugins = (
        (
            await session.execute(
                select(Plugin).where(Plugin.kind == "component").order_by(Plugin.name, Plugin.key)
            )
        )
        .scalars()
        .all()
    )
    return [plugin_registry.plugin_out(plugin) for plugin in plugins]


@router.get("/blocks", response_model=list[PluginBlockOut])
async def list_blocks(session: AsyncSession = Depends(get_session)):
    """所有已启用组件插件提供的区块，编辑器斜杠菜单使用。"""
    plugins = (
        (
            await session.execute(
                select(Plugin)
                .where(Plugin.enabled.is_(True), Plugin.kind == "component")
                .order_by(Plugin.name, Plugin.key)
            )
        )
        .scalars()
        .all()
    )
    return [block for plugin in plugins for block in plugin_registry.block_outputs(plugin)]


@router.get("/spec", response_model=dict)
async def plugin_spec():
    """组件插件开发规范：字段说明、AI 提示词与示例 manifest。"""
    component_example = {
        "manifest_version": MANIFEST_VERSION,
        "kind": "component",
        "key": "counter",
        "name": "计数器",
        "version": "1.0.0",
        "description": "可增减的计数卡片",
        "author": "Kiwi",
        "icon": "checkSquare",
        "homepage": "",
        "entry": "index.js",
        "style": "style.css",
        "blocks": [
            {
                "type": "counter",
                "label": "计数器",
                "icon": "checkSquare",
                "description": "可交互的计数卡片",
                "category": "效率",
                "default_props": {"label": "计数", "count": 0},
            }
        ],
        "settings": [],
    }
    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": "component",
        "package": "组件插件必须上传 .zip（plugin.json + 入口 JS + 可选 CSS）",
        "skill": "kiwi-plugin",
        "dev_kit_url": "/api/plugins/dev-kit",
        "ai_prompt": (
            "使用 kiwi-plugin skill 为 Kiwi 开发一个组件插件。先阅读 docs/PLUGIN_SPEC.md 与 "
            "docs/examples/plugins/（counter 最小示例、pomodoro / countdown 计时器示例），"
            "生成可直接压缩为 zip 的 plugin.json、入口 ESM "
            "与可选 style.css；入口必须导出 setup(host)，且只使用 host.vue / host.toast / "
            "host.theme。完成后用 /api/plugins/inspect 与导入接口验证 manifest。"
        ),
        "rules": [
            "插件仅支持组件插件：kind 必须为 component，且必须以 zip 交付",
            "key 为全局唯一小写 slug（字母、数字、连字符），发布后不可修改",
            "组件插件包含浏览器端 ESM，安装前必须确认第三方代码执行风险",
            "组件入口必须是单文件 ESM，导出 setup(host) 并返回 { blocks }",
            "展示颜色时使用 --kiwi-* CSS 变量或 host.theme，跟随系统主题色与学习模式，不要写死品牌色",
            "区块 type 在插件内唯一，最终标识为 `<插件 key>:<type>`",
            "单个插件最多 50 个区块，入口脚本不超过 2MB，样式不超过 512KB",
            "启用状态可按插件切换；停用后区块立即从编辑器菜单移除",
            "导入同 key 插件默认拒绝，勾选覆盖后原地更新",
        ],
        "fields": {
            "kind": "固定为 component（可交互代码组件）",
            "key": "插件唯一标识，^[a-z0-9][a-z0-9-]{1,63}$",
            "name": "显示名称（1-100 字符）",
            "version": "版本号（1-32 字符，建议 semver）",
            "description": "简介（最多 2000 字符）",
            "author": "作者（最多 100 字符）",
            "icon": "图标名，使用 Kiwi 内置图标（如 puzzle / checkSquare / star）",
            "homepage": "可选主页地址",
            "entry": "入口脚本在 zip 内的相对路径，默认 index.js",
            "style": "样式文件在 zip 内的相对路径，可选",
            "blocks[].type": "区块类型 slug（小写字母、数字、- 或 _）",
            "blocks[].label": "斜杠菜单中的名称",
            "blocks[].default_props": "组件插入时的默认 props（JSON 对象）",
            "blocks[].pinnable": "是否允许选中区块后置顶为跨路由浮窗（计时器等全局工具适用）",
            "host.theme": "组件运行时主题访问器：accent / accentStrong / accentSoft / shade(step, alpha)，并可用 --kiwi-* CSS 变量",
            "settings": "预留设置声明，当前只保存不解释",
        },
        "example": component_example,
        "examples": {"component": component_example},
    }


@router.get("/dev-kit", response_model=None)
async def plugin_dev_kit():
    """下载插件开发套件：完整规范、可运行示例与 AI skill。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in DEV_KIT_FILES:
            path = PROJECT_ROOT / relative
            if not path.is_file():
                continue
            archive.write(path, arcname=f"kiwi-plugin-dev-kit/{relative}")
        archive.writestr(
            "kiwi-plugin-dev-kit/AI_PROMPT.md",
            "# AI 插件开发提示词\n\n"
            "请使用 kiwi-plugin skill，并先阅读同目录下的 PLUGIN_SPEC.md 与 "
            "examples/plugins/（counter 最小示例、pomodoro / countdown 计时器示例）。"
            "输出一个可压缩为 zip 的 Kiwi 组件插件包，"
            "包含 plugin.json、index.js（导出 setup(host)）和可选 style.css；"
            "安装前用 `/api/plugins/inspect` 校验。\n",
        )
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="kiwi-plugin-dev-kit.zip"',
            "Cache-Control": "no-cache",
        },
    )


@router.post("/inspect", response_model=PluginInspectionOut)
async def inspect_plugin(file: UploadFile = File(...)):
    """导入预检：解析但不落库，供 UI 展示组件插件代码执行风险。"""
    raw = await _read_upload(file)
    if not raw:
        raise HTTPException(400, "插件包为空")
    return _inspection(_parse_package(raw, file.filename or ""))


@router.post("/import", response_model=PluginOut, status_code=201)
async def import_plugin(
    file: UploadFile = File(...),
    overwrite: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    raw = await _read_upload(file)
    if not raw:
        raise HTTPException(400, "插件包为空")
    package = _parse_package(raw, file.filename or "")
    manifest = package.manifest
    existing = (
        await session.execute(select(Plugin).where(Plugin.key == manifest.key))
    ).scalar_one_or_none()
    if existing is not None and not overwrite:
        raise HTTPException(409, f"插件 key 已存在：{manifest.key}，如需更新请勾选覆盖")
    plugin = existing or Plugin(key=manifest.key, enabled=True)
    plugin.source = "import"
    plugin_registry.apply_manifest(plugin, _package_manifest(package))
    plugin.entry = package.entry
    plugin.script = package.script
    plugin.style = package.style
    if plugin_registry.manifest_size(plugin.manifest) > MAX_MANIFEST_CHARS:
        raise HTTPException(400, "manifest 体积超出限制")
    if existing is None:
        session.add(plugin)
    await session.commit()
    await session.refresh(plugin)
    logger.info(
        "导入组件插件 %s v%s（%s）",
        plugin.key,
        plugin.version,
        "覆盖" if existing else "新增",
    )
    return plugin_registry.plugin_out(plugin)


@router.get("/{plugin_id}", response_model=PluginOut)
async def get_plugin(plugin_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    return plugin_registry.plugin_out(await _get_plugin(session, plugin_id))


@router.patch("/{plugin_id}", response_model=PluginOut)
async def update_plugin(
    plugin_id: uuid.UUID,
    data: PluginUpdate,
    session: AsyncSession = Depends(get_session),
):
    plugin = await _get_plugin(session, plugin_id)
    for field in (
        "name",
        "version",
        "description",
        "author",
        "icon",
        "homepage",
        "enabled",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(plugin, field, value)
    if data.blocks is not None:
        manifest = dict(plugin.manifest or {})
        manifest["blocks"] = [block.model_dump(mode="json") for block in data.blocks]
        plugin.manifest = manifest
    if plugin_registry.manifest_size(plugin.manifest) > MAX_MANIFEST_CHARS:
        raise HTTPException(400, "manifest 体积超出限制")
    await session.commit()
    await session.refresh(plugin)
    return plugin_registry.plugin_out(plugin)


@router.get("/{plugin_id}/bundle.js", response_model=None)
async def plugin_bundle(plugin_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    plugin = await _get_plugin(session, plugin_id)
    if plugin.kind != "component" or not plugin.script:
        raise HTTPException(404, "插件没有可执行入口")
    return Response(
        content=plugin.script,
        media_type="text/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{plugin_id}/style.css", response_model=None)
async def plugin_style(plugin_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    plugin = await _get_plugin(session, plugin_id)
    if not plugin.style:
        raise HTTPException(404, "插件没有样式文件")
    return Response(
        content=plugin.style,
        media_type="text/css; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{plugin_id}/export", response_model=None)
async def export_plugin(plugin_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    plugin = await _get_plugin(session, plugin_id)
    filename = f"{plugin.key}-{plugin.version}.zip"
    return Response(
        content=_export_zip(plugin),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.delete("/{plugin_id}", status_code=204)
async def delete_plugin(plugin_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    plugin = await _get_plugin(session, plugin_id)
    await session.delete(plugin)
    await session.commit()
