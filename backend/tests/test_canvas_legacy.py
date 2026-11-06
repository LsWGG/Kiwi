"""旧版 canvas_doc 的兼容读取。"""

from __future__ import annotations

from app.services.canvas_legacy import draw_doc_from_props, legacy_canvas_to_draw


def test_legacy_canvas_converts_nodes_and_edges():
    doc = {
        "version": 1,
        "theme": "engineering",
        "grid": True,
        "nodes": [
            {
                "id": "n1",
                "shape": "rect",
                "x": 20,
                "y": 30,
                "w": 180,
                "h": 72,
                "text": "需求梳理",
                "tone": "accent",
            },
            {
                "id": "n2",
                "shape": "ellipse",
                "x": 320,
                "y": 30,
                "w": 160,
                "h": 80,
                "text": "方案落地",
            },
        ],
        "edges": [
            {
                "id": "e1",
                "from": {"nodeId": "n1", "side": "right"},
                "to": {"nodeId": "n2", "side": "left"},
                "curve": "orthogonal",
                "arrow": "end",
                "label": "交付",
            }
        ],
    }

    draw = legacy_canvas_to_draw(doc)
    assert draw is not None
    assert draw["type"] == "jvs-draw"
    assert draw["appState"]["viewBackgroundColor"] == "#f8fafc"
    assert draw["appState"]["gridType"] == "dot"

    elements = {element["id"]: element for element in draw["elements"]}
    assert elements["n1"]["type"] == "rectangle"
    assert elements["n1"]["boundElements"] == [{"type": "text", "id": "n1-text"}]
    assert elements["n1-text"]["text"] == "需求梳理"
    assert elements["n1-text"]["containerId"] == "n1"
    assert elements["n2"]["type"] == "ellipse"
    assert elements["e1"]["type"] == "arrow"
    assert elements["e1"]["startBinding"]["elementId"] == "n1"
    assert elements["e1"]["endBinding"]["elementId"] == "n2"
    assert elements["e1"]["arrowType"] == "elbow"
    assert elements["e1-label"]["text"] == "交付"


def test_draw_doc_takes_priority_over_legacy_canvas():
    draw_doc = {"type": "jvs-draw", "version": 1, "elements": [], "appState": {}, "files": {}}
    props = {"draw_doc": draw_doc, "canvas_doc": {"nodes": [{"id": "old"}]}}
    assert draw_doc_from_props(props) is draw_doc


def test_invalid_legacy_canvas_returns_none():
    assert legacy_canvas_to_draw(None) is None
    assert legacy_canvas_to_draw({}) is None
    assert legacy_canvas_to_draw({"nodes": "not-a-list"}) is None
