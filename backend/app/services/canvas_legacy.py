"""旧版 canvas_doc 到 jvs-draw 文档的兼容读取。

升级画布后，笔记 props 里仍可能只有旧版的 ``canvas_doc``（节点 / 连线）。
分享、搜索与 Wiki 编译在读取时统一回退转换，旧笔记无需批量改库；用户下次
在画布里保存后会自然写成 ``draw_doc``。
"""

from __future__ import annotations

from typing import Any

TONE_NAMES = ("neutral", "accent", "green", "amber", "rose", "violet")

THEME_STYLES: dict[str, dict[str, Any]] = {
    "engineering": {
        "bg": "#f8fafc",
        "edge": "#64748b",
        "tones": {
            "neutral": ("#ffffff", "#cbd5e1", "#1e293b"),
            "accent": ("#e0f2fe", "#38bdf8", "#075985"),
            "green": ("#dcfce7", "#4ade80", "#166534"),
            "amber": ("#fef3c7", "#fbbf24", "#92400e"),
            "rose": ("#ffe4e6", "#fb7185", "#9f1239"),
            "violet": ("#ede9fe", "#a78bfa", "#5b21b6"),
        },
    },
    "blueprint": {
        "bg": "#0b1f3a",
        "edge": "#60a5fa",
        "tones": {
            "neutral": ("#102a4c", "#3b82f6", "#dbeafe"),
            "accent": ("#0c4a6e", "#38bdf8", "#e0f2fe"),
            "green": ("#064e3b", "#34d399", "#d1fae5"),
            "amber": ("#451a03", "#fbbf24", "#fef3c7"),
            "rose": ("#4c0519", "#fb7185", "#ffe4e6"),
            "violet": ("#2e1065", "#a78bfa", "#ede9fe"),
        },
    },
    "paper": {
        "bg": "#fbf7ef",
        "edge": "#78716c",
        "tones": {
            "neutral": ("#fffdf7", "#d6d3d1", "#44403c"),
            "accent": ("#ffedd5", "#fb923c", "#9a3412"),
            "green": ("#ecfccb", "#a3e635", "#3f6212"),
            "amber": ("#fef9c3", "#facc15", "#854d0e"),
            "rose": ("#ffe4e6", "#fb7185", "#9f1239"),
            "violet": ("#f3e8ff", "#c084fc", "#6b21a8"),
        },
    },
    "midnight": {
        "bg": "#0f172a",
        "edge": "#94a3b8",
        "tones": {
            "neutral": ("#1e293b", "#475569", "#e2e8f0"),
            "accent": ("#164e63", "#22d3ee", "#cffafe"),
            "green": ("#064e3b", "#34d399", "#d1fae5"),
            "amber": ("#451a03", "#fbbf24", "#fef3c7"),
            "rose": ("#4c0519", "#fb7185", "#ffe4e6"),
            "violet": ("#2e1065", "#c4b5fd", "#ede9fe"),
        },
    },
}

DEFAULT_THEME = THEME_STYLES["engineering"]


def _num(value: Any, fallback: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number == number else fallback  # 排除 NaN


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _theme(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str) and raw in THEME_STYLES:
        return THEME_STYLES[raw]
    return DEFAULT_THEME


def _tone(theme: dict[str, Any], tone: Any) -> tuple[str, str, str]:
    tones = theme["tones"]
    if isinstance(tone, str) and tone in tones:
        return tones[tone]
    return tones["neutral"]


def _base(
    element_id: str,
    element_type: str,
    x: float,
    y: float,
    width: float,
    height: float,
    extra: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": element_id,
        "type": element_type,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": "#94a3b8",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "strokeOpacity": 100,
        "roundness": None,
        "fontSize": 15,
        "fontFamily": "sans-serif",
        "fontColor": "#1e293b",
        "fontBgColor": "transparent",
        "textAlign": "center",
        "verticalAlign": "middle",
        "isDeleted": False,
        "groupIds": [],
        "boundElements": [],
        "lineHeight": 1.25,
        "letterSpacing": 0,
        **extra,
    }


def _text_element(
    element_id: str,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
    extra: dict[str, Any],
) -> dict[str, Any]:
    return _base(
        element_id,
        "text",
        x,
        y,
        width,
        height,
        {
            "text": text,
            "originalText": text,
            "strokeColor": "transparent",
            "backgroundColor": "transparent",
            "strokeWidth": 1,
            "roundness": None,
            "autoResize": False,
            **extra,
        },
    )


def _shape(node: dict[str, Any]) -> tuple[str, Any]:
    shape = _text(node.get("shape")) or "rect"
    if node.get("container") is True:
        return "rectangle", None
    if shape in ("round", "sticky"):
        return "rectangle", {"type": 3}
    if shape == "ellipse":
        return "ellipse", None
    if shape == "diamond":
        return "diamond", None
    if shape == "network":
        variant = node.get("variant")
        if variant == "database":
            return "cylinder", None
        if variant == "cloud":
            return "ellipse", None
        return "rectangle", {"type": 3}
    if shape in ("uml", "table"):
        return "rectangle", None
    return "rectangle", {"type": 3}


def _anchor_point(
    node: dict[str, Any] | None,
    side: Any,
    fallback_x: float,
    fallback_y: float,
) -> tuple[float, float]:
    if node is None:
        return fallback_x, fallback_y
    x = _num(node.get("x"))
    y = _num(node.get("y"))
    width = _num(node.get("w"))
    height = _num(node.get("h"))
    if side == "top":
        return x + width / 2, y
    if side == "right":
        return x + width, y + height / 2
    if side == "bottom":
        return x + width / 2, y + height
    if side == "left":
        return x, y + height / 2
    return x + width / 2, y + height / 2


def legacy_canvas_to_draw(raw: Any) -> dict[str, Any] | None:
    """把旧版 CanvasDoc 转成 jvs-draw 文档；不像旧画布时返回 None。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
        return None
    theme = _theme(raw.get("theme"))
    elements: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}

    for item in raw["nodes"]:
        if not isinstance(item, dict):
            continue
        node_id = _text(item.get("id"))
        if not node_id:
            continue
        nodes[node_id] = item
        x = _num(item.get("x"))
        y = _num(item.get("y"))
        width = max(0.0, _num(item.get("w")))
        height = max(0.0, _num(item.get("h")))
        text = _text(item.get("text"))
        align = "left" if item.get("align") == "left" else "center"
        font_size = max(8.0, _num(item.get("fontSize"), 15))
        tone = _tone(
            theme,
            "amber" if item.get("shape") == "sticky" and not item.get("tone") else item.get("tone"),
        )
        fill, stroke, font_color = tone
        bold = item.get("bold") is True

        if _text(item.get("shape")) == "text":
            lines = max(1, text.count("\n") + 1)
            elements.append(
                _text_element(
                    node_id,
                    text,
                    x,
                    y,
                    width or 200,
                    max(20.0, lines * font_size * 1.25),
                    {
                        "fontSize": font_size,
                        "fontColor": font_color,
                        "textAlign": align,
                        "verticalAlign": "top",
                        "fontWeight": "bold" if bold else "normal",
                        "isBold": bold,
                    },
                )
            )
            continue

        shape_type, roundness = _shape(item)
        is_container = item.get("container") is True
        text_id = f"{node_id}-text"
        has_text = bool(text.strip())
        elements.append(
            _base(
                node_id,
                shape_type,
                x,
                y,
                width,
                height,
                {
                    "roundness": roundness,
                    "strokeColor": theme["edge"] if is_container else stroke,
                    "backgroundColor": "transparent" if is_container else fill,
                    "strokeStyle": "dashed" if is_container else "solid",
                    "boundElements": [{"type": "text", "id": text_id}] if has_text else [],
                },
            )
        )
        if not has_text:
            continue
        lines = max(1, text.count("\n") + 1)
        text_height = max(font_size * 1.25, lines * font_size * 1.25)
        top = y + 6 if is_container else y + max(4.0, (height - text_height) / 2)
        elements.append(
            _text_element(
                text_id,
                text,
                x + 8,
                top,
                max(20.0, width - 16),
                text_height,
                {
                    "containerId": node_id,
                    "fontSize": font_size,
                    "fontColor": font_color,
                    "textAlign": "left" if is_container else align,
                    "verticalAlign": "top" if is_container else "middle",
                    "fontWeight": "bold" if bold else "normal",
                    "isBold": bold,
                },
            )
        )

    edges = raw.get("edges")
    if isinstance(edges, list):
        for item in edges:
            if not isinstance(item, dict):
                continue
            edge_id = _text(item.get("id")) or f"legacy-edge-{len(elements)}"
            from_anchor = item.get("from") if isinstance(item.get("from"), dict) else {}
            to_anchor = item.get("to") if isinstance(item.get("to"), dict) else {}
            from_id = _text(from_anchor.get("nodeId"))
            to_id = _text(to_anchor.get("nodeId"))
            start_x, start_y = _anchor_point(
                nodes.get(from_id), from_anchor.get("side"), _num(from_anchor.get("x")), _num(from_anchor.get("y"))
            )
            end_x, end_y = _anchor_point(
                nodes.get(to_id), to_anchor.get("side"), _num(to_anchor.get("x")), _num(to_anchor.get("y"))
            )
            dx = end_x - start_x
            dy = end_y - start_y
            label = _text(item.get("label")).strip()
            label_id = f"{edge_id}-label"
            curve = _text(item.get("curve"))
            arrow = _text(item.get("arrow")) or "end"
            _, stroke, font_color = _tone(theme, item.get("tone"))
            elements.append(
                _base(
                    edge_id,
                    "arrow",
                    start_x,
                    start_y,
                    abs(dx),
                    abs(dy),
                    {
                        "points": [[0, 0], [dx, dy]],
                        "startBinding": (
                            {"elementId": from_id, "focus": 0, "gap": 4, "isBorder": False}
                            if from_id
                            else None
                        ),
                        "endBinding": (
                            {"elementId": to_id, "focus": 0, "gap": 4, "isBorder": False}
                            if to_id
                            else None
                        ),
                        "startArrowhead": "arrow" if arrow == "both" else None,
                        "endArrowhead": None if arrow == "none" else "arrow",
                        "arrowType": (
                            "elbow" if curve == "orthogonal" else "curve" if curve == "bezier" else "sharp"
                        ),
                        "strokeColor": stroke,
                        "strokeStyle": "dashed" if item.get("dashed") is True else "solid",
                        "roundness": None,
                        "boundElements": [{"type": "text", "id": label_id}] if label else [],
                    },
                )
            )
            if label:
                elements.append(
                    _text_element(
                        label_id,
                        label,
                        (start_x + end_x) / 2 - 40,
                        (start_y + end_y) / 2 - 10,
                        80,
                        20,
                        {
                            "containerId": edge_id,
                            "fontSize": 12,
                            "fontColor": font_color,
                            "textAlign": "center",
                            "verticalAlign": "middle",
                        },
                    )
                )

    return {
        "type": "jvs-draw",
        "version": 1,
        "elements": elements,
        "appState": {
            "viewBackgroundColor": theme["bg"],
            **({"gridType": "dot"} if raw.get("grid") is True else {}),
        },
        "files": {},
        "updatedAt": 0,
    }


def draw_doc_from_props(props: Any) -> dict[str, Any] | None:
    """读取 draw_doc；旧笔记回退转换 canvas_doc。"""
    if not isinstance(props, dict):
        return None
    doc = props.get("draw_doc")
    if isinstance(doc, dict):
        return doc
    return legacy_canvas_to_draw(props.get("canvas_doc"))
