"""主题插件：画廊、启用、导入导出与开发套件。

主题插件复用组件插件的打包 / 校验 / 资产存储，但只允许声明式 JSON + CSS，
不执行 JavaScript。当前主题保存在 system_settings 单行表，覆盖值（背景、
透明度、强调色）与主题 key 一起持久化，全站共享。
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Plugin
from app.db.models.system_settings import SYSTEM_SETTINGS_ID, SystemSettings
from app.db.session import get_session
from app.routers.plugins import (
    _assets_for,
    _inspection,
    _parse_package,
    _read_upload,
    import_package_file,
)
from app.schemas.plugin import PluginInspectionOut, ThemeSpecIn
from app.schemas.theme import (
    ThemeActivateIn,
    ThemeActiveOut,
    ThemeBackgroundOut,
    ThemeOut,
    ThemeOverridesIn,
)
from app.services import builtin_themes, system_settings, theme_backgrounds

logger = logging.getLogger("kiwi.themes")

router = APIRouter(prefix="/api/themes", tags=["themes"])

DEV_KIT_ROOT = Path(__file__).resolve().parents[1] / "resources" / "plugin_dev_kit"
THEME_DEV_KIT_FILES = (
    "THEME_SPEC.md",
    "examples/themes/README.md",
    "examples/themes/aurora/plugin.json",
    "examples/themes/aurora/theme.css",
    "examples/themes/aurora/README.md",
    "examples/themes/aurora/assets/aurora.svg",
    "examples/themes/aurora/assets/preview.svg",
    "skill/kiwi-theme/SKILL.md",
)
DEFAULT_BUILTIN_KEY = builtin_themes.BUILTIN_THEMES[0]["key"]


def _overrides_from_row(row: SystemSettings | None) -> ThemeOverridesIn:
    if row is None or not row.theme_overrides:
        return ThemeOverridesIn()
    try:
        return ThemeOverridesIn.model_validate(row.theme_overrides)
    except ValidationError:
        logger.warning("主题覆盖配置损坏，已忽略")
        return ThemeOverridesIn()


def _active_key(row: SystemSettings | None) -> str:
    key = (row.active_theme if row else "") or DEFAULT_BUILTIN_KEY
    return key


def _background_refs(value: dict | None) -> set[str]:
    if not isinstance(value, dict):
        return set()
    refs = {
        str(value.get("background_image") or "").strip(),
        str(value.get("background_video") or "").strip(),
    }
    return {ref for ref in refs if ref}


def _asset_base(plugin: Plugin) -> str:
    return f"/api/plugins/{plugin.id}/asset/"


def _builtin_asset_base(theme: dict) -> str:
    if not builtin_themes.asset_paths(theme):
        return ""
    return f"/api/themes/builtin/{theme['key']}/asset/"


def _builtin_style_url(theme: dict) -> str:
    if not theme.get("style"):
        return ""
    return f"/api/themes/builtin/{theme['key']}/style.css"


def _builtin_preview_url(theme: dict) -> str:
    preview = str((theme.get("theme") or {}).get("preview") or "").strip()
    base = _builtin_asset_base(theme)
    if not preview or not base:
        return ""
    return f"{base}{preview.lstrip('/')}"


def _preview_url(plugin: Plugin, theme: ThemeSpecIn) -> str:
    if not theme.preview:
        return ""
    path = theme.preview.lstrip("/")
    if not path.startswith("assets/"):
        path = f"assets/{path}"
    return f"{_asset_base(plugin)}{path}"


def _theme_out_from_plugin(
    plugin: Plugin,
    assets: list[str],
    *,
    active: bool,
) -> ThemeOut | None:
    raw = (plugin.manifest or {}).get("theme")
    if not isinstance(raw, dict):
        return None
    try:
        spec = ThemeSpecIn.model_validate(raw)
    except ValidationError:
        logger.warning("主题插件 %s 的 theme 配置无效，已跳过", plugin.key)
        return None
    version_tag = int(plugin.updated_at.timestamp() * 1000) if plugin.updated_at else 0
    return ThemeOut(
        id=str(plugin.id),
        key=plugin.key,
        name=plugin.name,
        version=plugin.version,
        description=plugin.description,
        author=plugin.author,
        icon=plugin.icon or "palette",
        homepage=plugin.homepage,
        builtin=False,
        enabled=bool(plugin.enabled),
        active=active,
        style_url=(
            f"/api/plugins/{plugin.id}/style.css?v={version_tag}" if plugin.style else ""
        ),
        preview_url=_preview_url(plugin, spec),
        asset_base_url=_asset_base(plugin),
        theme=spec,
        assets=assets,
    )


def _builtin_out(theme: dict, *, active: bool) -> ThemeOut:
    spec = ThemeSpecIn.model_validate(theme["theme"])
    return ThemeOut(
        id=f"builtin:{theme['key']}",
        key=theme["key"],
        name=theme["name"],
        version=theme["version"],
        description=theme["description"],
        author=theme["author"],
        icon=theme["icon"],
        homepage=theme["homepage"],
        builtin=True,
        enabled=True,
        active=active,
        style_url=_builtin_style_url(theme),
        preview_url=_builtin_preview_url(theme),
        asset_base_url=_builtin_asset_base(theme),
        theme=spec,
        assets=list(builtin_themes.asset_paths(theme)),
    )


async def _installed_theme(
    session: AsyncSession, key: str
) -> Plugin | None:
    return (
        await session.execute(
            select(Plugin).where(
                Plugin.key == key,
                Plugin.kind == "theme",
            )
        )
    ).scalar_one_or_none()


async def _active_payload(session: AsyncSession) -> ThemeActiveOut:
    row = await system_settings.get_row(session)
    key = _active_key(row)
    overrides = _overrides_from_row(row)
    builtin = builtin_themes.get_builtin(key)
    if builtin is not None:
        return ThemeActiveOut(
            key=builtin["key"],
            name=builtin["name"],
            builtin=True,
            enabled=True,
            theme=ThemeSpecIn.model_validate(builtin["theme"]),
            style_url=_builtin_style_url(builtin),
            asset_base_url=_builtin_asset_base(builtin),
            overrides=overrides,
        )
    plugin = await _installed_theme(session, key)
    if plugin is None or not plugin.enabled:
        fallback = builtin_themes.get_builtin(DEFAULT_BUILTIN_KEY)
        assert fallback is not None
        return ThemeActiveOut(
            key=fallback["key"],
            name=fallback["name"],
            builtin=True,
            enabled=True,
            theme=ThemeSpecIn.model_validate(fallback["theme"]),
            style_url=_builtin_style_url(fallback),
            asset_base_url=_builtin_asset_base(fallback),
            overrides=ThemeOverridesIn(),
        )
    raw = (plugin.manifest or {}).get("theme")
    try:
        spec = ThemeSpecIn.model_validate(raw) if isinstance(raw, dict) else None
    except ValidationError:
        spec = None
    if spec is None:
        fallback = builtin_themes.get_builtin(DEFAULT_BUILTIN_KEY)
        assert fallback is not None
        return ThemeActiveOut(
            key=fallback["key"],
            name=fallback["name"],
            builtin=True,
            enabled=True,
            theme=ThemeSpecIn.model_validate(fallback["theme"]),
            style_url=_builtin_style_url(fallback),
            asset_base_url=_builtin_asset_base(fallback),
            overrides=ThemeOverridesIn(),
        )
    version_tag = int(plugin.updated_at.timestamp() * 1000) if plugin.updated_at else 0
    return ThemeActiveOut(
        key=plugin.key,
        name=plugin.name,
        builtin=False,
        enabled=True,
        theme=spec,
        style_url=(
            f"/api/plugins/{plugin.id}/style.css?v={version_tag}" if plugin.style else ""
        ),
        asset_base_url=_asset_base(plugin),
        overrides=overrides,
    )


@router.get("", response_model=list[ThemeOut])
async def list_themes(session: AsyncSession = Depends(get_session)):
    row = await system_settings.get_row(session)
    active_key = _active_key(row)
    items: list[ThemeOut] = [
        _builtin_out(theme, active=theme["key"] == active_key)
        for theme in builtin_themes.BUILTIN_THEMES
    ]
    plugins = (
        (
            await session.execute(
                select(Plugin).where(Plugin.kind == "theme").order_by(Plugin.name, Plugin.key)
            )
        )
        .scalars()
        .all()
    )
    for plugin in plugins:
        # 极光已升级为内置主题；旧库里可能还留着同名安装记录，跳过避免重复。
        if plugin.key in builtin_themes.BUILTIN_KEYS:
            continue
        assets = await _assets_for(session, plugin.id)
        item = _theme_out_from_plugin(
            plugin,
            [asset.path for asset in assets],
            active=plugin.key == active_key,
        )
        if item is not None:
            items.append(item)
    # 画廊顺序：当前主题置顶，其次内置主题，最后已安装主题；同组按名称排序。
    items.sort(key=lambda item: (not item.active, not item.builtin, item.name.casefold()))
    return items


@router.get("/active", response_model=ThemeActiveOut)
async def active_theme(session: AsyncSession = Depends(get_session)):
    return await _active_payload(session)


@router.put("/active", response_model=ThemeActiveOut)
async def activate_theme(
    data: ThemeActivateIn,
    session: AsyncSession = Depends(get_session),
):
    key = data.key.strip()
    if key not in builtin_themes.BUILTIN_KEYS:
        plugin = await _installed_theme(session, key)
        if plugin is None:
            raise HTTPException(404, f"主题不存在：{key}")
        if not plugin.enabled:
            raise HTTPException(400, f"主题已停用，请先启用：{key}")
    row = await system_settings.get_row(session)
    if row is None:
        row = SystemSettings(id=SYSTEM_SETTINGS_ID)
        session.add(row)
    old_backgrounds = _background_refs(row.theme_overrides)
    row.active_theme = key
    if data.overrides is not None:
        row.theme_overrides = data.overrides.model_dump(mode="json", exclude_none=True)
    await session.commit()
    if data.overrides is not None:
        # 背景文件在提交成功后清理，避免保存失败把仍在使用的背景删掉。
        theme_backgrounds.prune_replaced(
            old_backgrounds, _background_refs(row.theme_overrides)
        )
    return await _active_payload(session)


@router.post("/background", response_model=ThemeBackgroundOut, status_code=201)
async def upload_background(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """上传自定义背景（图片 / 动图 / 视频，≤100MB），返回站内 /media URL。"""
    try:
        stored = await theme_backgrounds.save_upload(file)
    except theme_backgrounds.BackgroundTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except theme_backgrounds.BackgroundUnsupported as exc:
        raise HTTPException(415, str(exc)) from exc
    row = await system_settings.get_row(session)
    referenced = _background_refs(row.theme_overrides if row else None)
    theme_backgrounds.prune_orphans(referenced | {stored.url})
    return ThemeBackgroundOut(
        url=stored.url,
        kind=stored.kind,
        content_type=stored.content_type,
        size=stored.size,
    )


@router.delete("/background", status_code=204)
async def delete_background(
    url: str = Query(..., min_length=1, max_length=2000),
    session: AsyncSession = Depends(get_session),
):
    """删除未被当前覆盖值引用的上传背景，用于取消编辑时清理文件。"""
    row = await system_settings.get_row(session)
    if url in _background_refs(row.theme_overrides if row else None):
        raise HTTPException(400, "该背景正在使用，请先保存新的背景或恢复默认")
    if not theme_backgrounds.remove_url(url):
        raise HTTPException(404, "背景文件不存在")
    return Response(status_code=204)


@router.post("/inspect", response_model=PluginInspectionOut)
async def inspect_theme(file: UploadFile = File(...)):
    raw = await _read_upload(file)
    if not raw:
        raise HTTPException(400, "主题包为空")
    package = _parse_package(raw, file.filename or "")
    if package.manifest.kind != "theme":
        raise HTTPException(400, "这不是主题插件：plugin.json 的 kind 必须为 theme")
    return _inspection(package)


@router.post("/import", response_model=ThemeOut, status_code=201)
async def import_theme(
    file: UploadFile = File(...),
    overwrite: bool = Query(False),
    session: AsyncSession = Depends(get_session),
):
    # 先预检，避免把组件插件误存为主题。
    raw = await _read_upload(file)
    if not raw:
        raise HTTPException(400, "主题包为空")
    package = _parse_package(raw, file.filename or "")
    if package.manifest.kind != "theme":
        raise HTTPException(400, "这不是主题插件：plugin.json 的 kind 必须为 theme")
    if package.manifest.key in builtin_themes.BUILTIN_KEYS:
        raise HTTPException(409, f"主题 key 与内置主题冲突：{package.manifest.key}")
    if not package.style and not package.manifest.theme.colors:
        raise HTTPException(400, "主题至少需要声明 colors 或 theme.css")
    # 复用插件落库逻辑（manifest / style / assets）。
    upload = UploadFile(filename=file.filename, file=io.BytesIO(raw))
    plugin = await import_package_file(
        upload, overwrite, session, expected_kind="theme"
    )
    assets = await _assets_for(session, plugin.id)
    item = _theme_out_from_plugin(
        plugin, [asset.path for asset in assets], active=False
    )
    if item is None:
        raise HTTPException(400, "主题配置无效")
    logger.info("导入主题插件 %s v%s", plugin.key, plugin.version)
    return item


@router.get("/spec", response_model=dict)
async def theme_spec():
    """主题插件开发规范：字段说明、AI 提示词与示例 manifest。"""
    example = {
        "manifest_version": 1,
        "kind": "theme",
        "key": "aurora",
        "name": "极光",
        "version": "1.0.0",
        "description": "深色极光渐变主题",
        "author": "Kiwi",
        "icon": "palette",
        "homepage": "",
        "entry": "",
        "style": "theme.css",
        "blocks": [],
        "theme": {
            "mode": "dark",
            "colors": {
                "app.background": "#0b1020",
                "surface.background": "#121a30",
                "surface.muted": "#1a2540",
                "surface.strong": "#253356",
                "border.subtle": "#1c2742",
                "border.default": "#2a3a5e",
                "border.strong": "#3b4f7a",
                "text.primary": "#e7ecff",
                "text.strong": "#d3ddfc",
                "text.secondary": "#b1bfe8",
                "text.muted": "#8b9bc4",
                "text.subtle": "#6f7fa8",
                "text.faint": "#56668c",
                "accent": "#5eead4",
                "accent.foreground": "#062a25",
            },
            "background": {
                "image": "assets/aurora.svg",
                "size": "cover",
                "position": "center",
                "repeat": "no-repeat",
                "dim": 0.25,
                "blur": 2,
            },
            "surface": {"opacity": 0.82, "blur": 14},
            "typography": {"body": "", "heading": "", "mono": ""},
            "preview": "assets/preview.svg",
        },
    }
    return {
        "manifest_version": 1,
        "kind": "theme",
        "package": "主题插件必须上传 .zip（plugin.json + 可选 theme.css + assets/）",
        "skill": "kiwi-theme",
        "dev_kit_url": "/api/themes/dev-kit",
        "ai_prompt": (
            "使用 kiwi-theme skill 为 Kiwi 开发一个主题插件。先阅读 docs/THEME_SPEC.md "
            "与 docs/examples/themes/aurora/，输出可直接压缩为 zip 的 plugin.json、"
            "可选 theme.css 与 assets/ 资源。主题只允许声明式 JSON + CSS，不执行 JavaScript；"
            "颜色令牌必须使用规范中的 key，装饰样式限定在 html[data-kiwi-theme=\"<key>\"] 下。"
            "完成后用 /api/themes/inspect 校验并导入。"
        ),
        "rules": [
            "主题插件 kind 必须为 theme，且必须以 zip 交付",
            "key 为全局唯一小写 slug（字母、数字、连字符），发布后不可修改；不能与内置主题重名",
            "主题只包含 plugin.json / theme.css / assets/，禁止 JavaScript",
            "颜色令牌只允许规范列出的 key；未知 key 会被拒绝",
            "背景图与预览图放在 assets/ 下，单文件不超过 4MB，整包不超过 10MB",
            "theme.css 必须用 html[data-kiwi-theme=\"<key>\"] 限定作用域，避免影响其他主题",
            "透明度 opacities 过低会影响可读性，surface.opacity 最低 0.35",
            "深色主题请把 mode 设为 dark，并同时覆盖文本、边框与表面色阶",
            "主题会作用于全站界面（含弹窗、编辑器、表格），请逐页截图检查",
            "字体可通过 @font-face 引用 assets/ 下的字体文件",
        ],
        "fields": {
            "kind": "固定为 theme",
            "key": "主题唯一标识，^[a-z0-9][a-z0-9-]{1,63}$",
            "name": "显示名称（1-100 字符）",
            "version": "版本号（1-32 字符，建议 semver）",
            "description": "简介（最多 2000 字符）",
            "author": "作者（最多 100 字符）",
            "icon": "图标名（palette / sparkle / brush 等 Kiwi 内置图标）",
            "style": "theme.css 在 zip 内的相对路径，可选",
            "theme.mode": "light / dark，决定 color-scheme",
            "theme.colors": "颜色令牌：app.background / surface.* / border.* / text.* / accent",
            "theme.background": "背景图、填充方式、暗化 dim 与模糊 blur",
            "theme.surface": "面板不透明度 opacity、毛玻璃 blur",
            "theme.typography": "body / heading / mono 字体栈",
            "theme.preview": "主题画廊缩略图（assets/ 下相对路径）",
            "assets/": "背景图、预览图、字体等二进制资源",
        },
        "example": example,
        "examples": {"theme": example},
    }


@router.get("/dev-kit", response_model=None)
async def theme_dev_kit():
    """下载主题开发套件：规范、示例主题与 AI skill。"""
    missing = [
        relative for relative in THEME_DEV_KIT_FILES if not (DEV_KIT_ROOT / relative).is_file()
    ]
    if missing:
        logger.error("主题开发套件资源缺失：%s", ", ".join(missing))
        raise HTTPException(
            500,
            "主题开发套件资源缺失，请确认后端镜像包含 app/resources/plugin_dev_kit。",
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in THEME_DEV_KIT_FILES:
            path = DEV_KIT_ROOT / relative
            archive.write(path, arcname=f"kiwi-theme-dev-kit/{relative}")
        archive.writestr(
            "kiwi-theme-dev-kit/AI_PROMPT.md",
            "# AI 主题开发提示词\n\n"
            "请先阅读 skill/kiwi-theme/SKILL.md 与 THEME_SPEC.md，再参考 "
            "examples/themes/aurora/。输出一个可压缩为 zip 的 Kiwi 主题插件包，"
            "包含 plugin.json、可选 theme.css 与 assets/；颜色令牌只能使用规范中的 key。"
            "安装前用 `/api/themes/inspect` 校验。\n",
        )
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="kiwi-theme-dev-kit.zip"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("/builtin/{key}/export", response_model=None)
async def export_builtin_theme(key: str):
    theme = builtin_themes.get_builtin(key)
    if theme is None:
        raise HTTPException(404, "内置主题不存在")
    return Response(
        content=builtin_themes.export_zip(theme),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{theme["key"]}-{theme["version"]}.zip"',
            "Cache-Control": "no-cache",
        },
    )


@router.get("/builtin/{key}/style.css", response_model=None)
async def builtin_theme_style(key: str):
    theme = builtin_themes.get_builtin(key)
    if theme is None or not theme.get("style"):
        raise HTTPException(404, "内置主题没有样式文件")
    return Response(
        content=builtin_themes.read_style(theme),
        media_type="text/css; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/builtin/{key}/asset/{path:path}", response_model=None)
async def builtin_theme_asset(key: str, path: str):
    theme = builtin_themes.get_builtin(key)
    if theme is None:
        raise HTTPException(404, "内置主题不存在")
    normalized = path.replace("\\", "/").lstrip("/")
    if ".." in PurePosixPath(normalized).parts:
        raise HTTPException(400, "资源路径非法")
    if normalized not in builtin_themes.asset_paths(theme):
        raise HTTPException(404, "资源不存在")
    return Response(
        content=builtin_themes.read_asset(theme, normalized),
        media_type=builtin_themes.asset_media_type(normalized),
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
