"""主题自定义覆盖的存取：按主题 key 分组持久化。

``system_settings.theme_overrides`` 历史上只保存当前激活主题的一份扁平覆盖
值。引入按主题保留后，JSON 结构变为 ``{ "<theme-key>": { ...覆盖值 } }``。
读取旧数据时自动归到当前激活主题，下一次写入时完成迁移，无需数据库迁移。
"""

from __future__ import annotations

from pydantic import ValidationError

from app.schemas.theme import ThemeOverridesIn

# 旧版扁平结构里会出现这些字段；新结构的外层 key 是主题 key。
_OVERRIDE_FIELDS = frozenset(ThemeOverridesIn.model_fields)


def split_stored(raw: dict | None, active_key: str) -> dict[str, dict]:
    """把数据库 JSON 归一化为 ``{主题 key: 覆盖值 dict}``。"""
    if not isinstance(raw, dict) or not raw:
        return {}
    if any(key in _OVERRIDE_FIELDS for key in raw):
        return {active_key: dict(raw)} if active_key else {}
    return {
        str(key): dict(value)
        for key, value in raw.items()
        if isinstance(value, dict)
    }


def overrides_for(raw: dict | None, active_key: str) -> ThemeOverridesIn:
    """读取某个主题的覆盖值；缺失或损坏时回落到空覆盖。"""
    value = split_stored(raw, active_key).get(active_key)
    if not isinstance(value, dict):
        return ThemeOverridesIn()
    try:
        return ThemeOverridesIn.model_validate(value)
    except ValidationError:
        return ThemeOverridesIn()


def background_refs(value: dict | None) -> set[str]:
    """一份覆盖值里引用的站内 / 远程背景 URL。"""
    if not isinstance(value, dict):
        return set()
    refs = {
        str(value.get("background_image") or "").strip(),
        str(value.get("background_video") or "").strip(),
    }
    return {ref for ref in refs if ref}


def stored_refs(stored: dict[str, dict]) -> set[str]:
    refs: set[str] = set()
    for value in stored.values():
        refs |= background_refs(value)
    return refs


def all_background_refs(raw: dict | None, active_key: str) -> set[str]:
    """所有主题覆盖值引用的背景 URL。"""
    return stored_refs(split_stored(raw, active_key))


def without_theme(
    raw: dict | None, active_key: str, key: str
) -> tuple[dict[str, dict], set[str]]:
    """删除某个主题的覆盖值。

    返回 ``(新结构, 只被该主题引用、可以安全删除的背景 URL)``；仍被其他
    主题引用的 URL 不会出现在第二个返回值里。
    """
    stored = split_stored(raw, active_key)
    removed = stored.pop(key, None)
    removed_refs = background_refs(removed) if isinstance(removed, dict) else set()
    return stored, removed_refs - stored_refs(stored)
