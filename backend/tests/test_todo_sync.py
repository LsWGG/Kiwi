"""待办汇总：时间轴组件节点中的任务提取与双向状态同步。"""

from __future__ import annotations

import json
from hashlib import sha1

from app.services.todo_sync import (
    plugin_fences,
    plugin_task_items,
    plugin_task_label,
    plugin_task_location,
    set_plugin_task_state,
    task_items,
)


def _payload(points: list[dict], *, title: str = "项目时间轴") -> str:
    return json.dumps(
        {
            "plugin": "timeline",
            "block": "timeline",
            "props": {"title": title, "points": points},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _body(payload: str, *, fence: str = "````") -> str:
    return (
        "正文开始\n\n"
        f"{fence}kiwi-plugin\n"
        f"{payload}\n"
        f"{fence}\n\n"
        "正文结束\n"
    )


def _points() -> list[dict]:
    return [
        {
            "id": "p1",
            "time": "09:00",
            "summary": "晨会",
            "content": "会议纪要\n\n- [ ] 整理周报\n- [x] 发送邀请\n- [ ] 整理周报",
            "key": False,
        },
        {
            "id": "p2",
            "time": "14:00",
            "summary": "开发",
            "content": "- [ ] 修复时间轴定位",
            "key": True,
        },
    ]


def _ref(text: str) -> str:
    return f"task:{sha1(text.encode('utf-8')).hexdigest()[:16]}:1"


def test_task_items_still_extracts_top_level_tasks():
    assert task_items("- [ ] 普通任务\n- [x] 已完成") == [
        (_ref("普通任务"), "普通任务", False),
        (_ref("已完成"), "已完成", True),
    ]


def test_plugin_task_items_extracts_timeline_points_in_document_order():
    tasks = plugin_task_items(_body(_payload(_points())))

    assert [(task.text, task.checked) for task in tasks] == [
        ("整理周报", False),
        ("发送邀请", True),
        ("整理周报", False),
        ("修复时间轴定位", False),
    ]
    # 同一时间点里的同名任务按出现顺序编号，ref 不重复。
    assert tasks[0].ref != tasks[2].ref
    assert len({task.ref for task in tasks}) == 4
    assert tasks[0].point_index == 0 and tasks[0].task_index == 0
    assert tasks[2].point_index == 0 and tasks[2].task_index == 2
    assert tasks[3].point_id == "p2" and tasks[3].task_index == 0
    assert plugin_task_label(tasks[0]) == "项目时间轴 · 09:00 · 晨会：整理周报"


def test_plugin_task_items_ignores_other_plugins_and_broken_fences():
    counter = json.dumps(
        {
            "plugin": "counter",
            "block": "counter",
            "props": {"content": "- [ ] 这不是时间轴任务"},
        }
    )
    body = _body(counter) + "\n````kiwi-plugin\n{不是 JSON}\n````\n"
    assert plugin_task_items(body) == []
    # 无法解析的围栏仍占用文档序号，保证后续区块的 ref 稳定。
    fences = plugin_fences(body)
    assert [fence.index for fence in fences] == [0, 1]
    assert fences[0].payload is not None
    assert fences[1].payload is None


def test_set_plugin_task_state_toggles_only_target_and_preserves_body():
    body = _body(_payload(_points()))
    target = plugin_task_items(body)[0]

    updated = set_plugin_task_state(body, target.ref, True)

    assert updated is not None
    tasks = plugin_task_items(updated)
    assert tasks[0].checked is True
    assert [task.checked for task in tasks[1:]] == [True, False, False]
    assert updated.startswith("正文开始\n\n````kiwi-plugin\n")
    assert updated.endswith("````\n\n正文结束\n")
    # 其余 props 原样保留。
    payload = plugin_fences(updated)[0].payload
    assert payload["props"]["points"][1]["key"] is True
    assert payload["props"]["points"][0]["summary"] == "晨会"


def test_set_plugin_task_state_finds_point_after_block_moved():
    original = _body(_payload(_points()))
    target = plugin_task_items(original)[0]
    other = _body(_payload([{"id": "x1", "time": "08:00", "summary": "其他", "content": "- [ ] 别的任务"}]))
    moved = other + "\n" + original

    updated = set_plugin_task_state(moved, target.ref, True)

    assert updated is not None
    tasks = plugin_task_items(updated)
    assert [(task.point_id, task.text, task.checked) for task in tasks] == [
        ("x1", "别的任务", False),
        ("p1", "整理周报", True),
        ("p1", "发送邀请", True),
        ("p1", "整理周报", False),
        ("p2", "修复时间轴定位", False),
    ]


def test_set_plugin_task_state_supports_points_without_id():
    points = [{"time": "10:00", "summary": "无 id", "content": "- [ ] 旧数据任务"}]
    body = _body(_payload(points))
    task = plugin_task_items(body)[0]
    assert task.ref.split(":")[2] == "i0"

    updated = set_plugin_task_state(body, task.ref, True)
    assert updated is not None
    assert plugin_task_items(updated)[0].checked is True


def test_plugin_task_location_returns_point_and_task_indices():
    body = _body(_payload(_points()))
    target = plugin_task_items(body)[3]

    assert plugin_task_location(body, target.ref) == {
        "plugin_block_index": 0,
        "plugin_point_id": "p2",
        "plugin_point_index": 1,
        "plugin_point_time": "14:00",
        "plugin_point_summary": "开发",
        "plugin_task_index": 0,
    }
    assert plugin_task_location(body, "plugin:0:deadbeef0000:0000000000000000:1") is None
