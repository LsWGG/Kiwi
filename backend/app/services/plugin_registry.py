"""插件 manifest 规范化与区块拍平。"""

from __future__ import annotations

import json
from typing import Any

from app.db.models import Plugin
from app.schemas.plugin import PluginBlockOut, PluginManifestIn, PluginOut


def manifest_to_dict(manifest: PluginManifestIn) -> dict[str, Any]:
    """转为可持久化的规范化字典；key / 元信息同步到独立列。"""
    return manifest.model_dump(mode="json")


def apply_manifest(plugin: Plugin, manifest: PluginManifestIn) -> None:
    plugin.key = manifest.key
    plugin.name = manifest.name
    plugin.version = manifest.version
    plugin.description = manifest.description
    plugin.author = manifest.author
    plugin.icon = manifest.icon or "puzzle"
    plugin.homepage = manifest.homepage
    plugin.kind = manifest.kind
    plugin.entry = manifest.entry if manifest.kind == "component" else ""
    plugin.manifest = manifest_to_dict(manifest)


def _default_props(block: dict[str, Any]) -> dict[str, Any]:
    value = block.get("default_props")
    return value if isinstance(value, dict) else {}


def block_outputs(plugin: Plugin) -> list[PluginBlockOut]:
    rows: list[PluginBlockOut] = []
    for block in plugin.blocks:
        block_type = str(block.get("type") or "").strip()
        template = str(block.get("template_markdown") or "")
        if not block_type:
            continue
        # 模板插件必须带模板；组件插件允许只有 type + 默认属性。
        if plugin.kind == "template" and not template:
            continue
        rows.append(
            PluginBlockOut(
                key=f"{plugin.key}:{block_type}",
                plugin_key=plugin.key,
                plugin_name=plugin.name,
                plugin_version=plugin.version,
                type=block_type,
                label=str(block.get("label") or block_type),
                icon=str(block.get("icon") or "puzzle"),
                description=str(block.get("description") or ""),
                category=str(block.get("category") or "插件区块"),
                kind="component" if plugin.kind == "component" else "template",
                template_markdown=template,
                default_props=_default_props(block),
                pinnable=bool(block.get("pinnable")),
            )
        )
    return rows


def plugin_out(plugin: Plugin) -> PluginOut:
    kind = "component" if plugin.kind == "component" else "template"
    has_script = kind == "component" and bool(plugin.script)
    version_tag = int(plugin.updated_at.timestamp() * 1000) if plugin.updated_at else 0
    return PluginOut(
        id=plugin.id,
        key=plugin.key,
        name=plugin.name,
        version=plugin.version,
        description=plugin.description,
        author=plugin.author,
        icon=plugin.icon,
        homepage=plugin.homepage,
        enabled=plugin.enabled,
        kind=kind,
        entry=plugin.entry or ("index.js" if kind == "component" else ""),
        source=plugin.source,
        has_script=has_script,
        has_style=bool(plugin.style),
        script_size=len(plugin.script or ""),
        style_size=len(plugin.style or ""),
        script_url=(f"/api/plugins/{plugin.id}/bundle.js?v={version_tag}" if has_script else ""),
        style_url=(f"/api/plugins/{plugin.id}/style.css?v={version_tag}" if plugin.style else ""),
        blocks=block_outputs(plugin),
        created_at=plugin.created_at,
        updated_at=plugin.updated_at,
    )


def manifest_size(manifest: dict[str, Any]) -> int:
    return len(json.dumps(manifest, ensure_ascii=False))
