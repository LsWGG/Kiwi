"""生成内置演示知识库 seed 与随包素材。

演示库主线：一个刚接触 Kiwi 的用户，通过「三周搭建团队知识库」的示例项目，
完整走一遍 笔记 → Wiki → 图谱 → 学习 → 复习 → 考试 的闭环。所有内容都围绕
Kiwi 自身功能展开，读完后可以直接照着操作。

运行：
    cd backend && uv run python scripts/build_builtin_demo.py
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "services" / "builtin_demo_assets"
UPLOADS = ASSETS / "uploads"
MEDIA = ASSETS / "media"

KB_ID = uuid.UUID("6f3a1c2e-8b4d-4e9a-9c7f-2a5d8e1b4c60")
NS = uuid.UUID("c2b7e4a1-5d3f-4a8c-9e6b-1f0d2c3a4b5e")
BASE = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def ts(minutes: int = 0) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat()


def iso(dt: datetime) -> str:
    return dt.isoformat()


# --------------------------------------------------------------------------- #
# 目录 / 标签
# --------------------------------------------------------------------------- #

FOLDERS = [
    ("start", "00 从这里开始", 0),
    ("workspace", "01 笔记工作区", 1),
    ("wiki", "02 Wiki 与知识图谱", 2),
    ("study", "03 学习与复习", 3),
    ("project", "04 示例项目", 4),
    # 名称必须精确为「收件箱」：工作区会把这个分组自动置顶并启用收件箱配色。
    ("inbox", "收件箱", 5),
]

TAGS = [
    ("start", "入门"),
    ("notes", "笔记"),
    ("editor", "编辑器"),
    ("canvas", "画布"),
    ("database", "数据表"),
    ("notebook", "Notebook"),
    ("import", "导入"),
    ("link", "外链"),
    ("wiki", "Wiki"),
    ("graph", "图谱"),
    ("study", "学习"),
    ("review", "复习"),
    ("template", "模板"),
    ("project", "项目"),
]

FOLDER_ID = {key: uid(f"folder:{key}") for key, _, _ in FOLDERS}
TAG_ID = {key: uid(f"tag:{key}") for key, _ in TAGS}


# --------------------------------------------------------------------------- #
# 笔记模板
# --------------------------------------------------------------------------- #

TEMPLATES = [
    {
        "key": "experience",
        "name": "功能体验记录",
        "description": "每体验一个功能，用固定结构记录操作路径、结果与改进点。",
        "icon": "book",
        "title_pattern": "体验记录：{功能名}",
        "tags": ["入门", "笔记"],
        "body_md": """# 体验记录：

> 体验日期：
> 体验人：
> 所属模块：

## 我想完成什么


## 操作路径

1.
2.

## 实际结果

- [ ] 符合预期
- [ ] 需要改进

## 观察记录

| 观察点 | 结果 | 备注 |
|---|---|---|
| 入口是否好找 |  |  |
| 操作是否顺畅 |  |  |
| 结果是否可预期 |  |  |

## 下一步

- [ ]
""",
    },
    {
        "key": "weekly",
        "name": "每周学习复盘",
        "description": "汇总一周的学习时长、正确率与薄弱点，决定下周重点。",
        "icon": "calendar",
        "title_pattern": "第 {周次} 周学习复盘",
        "tags": ["学习", "复习"],
        "body_md": """# 第 {周次} 周学习复盘

> 周期：____-__-__ 至 ____-__-__

## 本周数据

| 指标 | 数值 |
|---|---|
| 学习时长 |  |
| 完成题数 |  |
| 正确率 |  |
| 到期复习 |  |
| 仿真考试 |  |

## 学到的三件事

1.
2.
3.

## 仍然薄弱

-

## 下周计划

- [ ]
""",
    },
]


# --------------------------------------------------------------------------- #
# 笔记内容
# --------------------------------------------------------------------------- #

NOTES: list[dict] = []


def add_note(
    key: str,
    title: str,
    folder: str,
    body: str = "",
    *,
    kind: str = "doc",
    tags: tuple[str, ...] = (),
    props: dict | None = None,
    sort: int = 0,
    source_key: str | None = None,
    wiki_slug: str | None = None,
    pinned: bool = False,
    minutes: int = 0,
) -> str:
    note_props = dict(props or {})
    if wiki_slug:
        note_props["wiki_page_id"] = uid(f"wiki:{wiki_slug}")
    if pinned:
        note_props["pinned"] = True
    NOTES.append(
        {
            "key": key,
            "id": uid(f"note:{key}"),
            "title": title,
            "body_md": body.strip(),
            "kind": kind,
            "folder": folder,
            "tags": tags,
            "props": note_props,
            "sort": sort,
            "source_key": source_key,
            "minutes": minutes,
        }
    )
    return key


add_note(
    "welcome",
    "欢迎使用 Kiwi",
    "start",
    """
# 欢迎使用 Kiwi

这是一个随系统内置的**功能演示知识库**。它不是互不相关的测试数据，而是一份可以照着操作的上手手册：每篇笔记对应 Kiwi 的一个真实能力，并且通过双向链接连成一张可浏览、可检索、可学习的网络。

> 你可以随意编辑或删除本库。删除后，在「知识库」页的内置库卡片上点击「还原」即可恢复出厂内容。

## 这个库能带你走完什么

| 你会用到 | 对应笔记 | 你会看到 |
|---|---|---|
| 笔记工作区 | [[文档编辑与块命令]] | 块命令、表格、任务列表、图片 |
| 画布 | [[画布：把关系画出来]] | 工程图、思维导图、主题切换 |
| 数据表 | [[数据表示例 · 功能体验清单]] | 表格 / 看板 / 画册 / 日历 |
| Notebook | [[Notebook 示例 · 学习记录分析]] | 代码、输出与结论同页 |
| 导入与抓取 | [[导入示例 · Kiwi 功能速查表]]、[[外链示例 · AntV G6 文档]] | 文件解析、网页正文 |
| Wiki 与图谱 | [[Wiki 编译：从笔记长出页面]]、[[知识图谱：星图怎么读]] | 编译、双向链接、星空图谱 |
| 学习闭环 | [[学习模式：把 Wiki 变成课程]]、[[复习与仿真考试]] | 出题、复习、仿真考试 |

## 建议的体验顺序

1. 先读 [[一分钟上手]]，用十分钟完成一次完整闭环；
2. 打开 [[画布示例 · Kiwi 功能全景]]，拖动节点，试试智能粘连、对齐辅助与主题切换；
3. 在数据表里切换四种视图，把一张卡片拖到另一个分组；
4. 进入「学习」模式完成一次五题练习，再查看复习队列；
5. 回到 Wiki，悬停一颗星球，观察关系如何被点亮。

## 关于示例项目

本库中有一条贯穿主线：[[示例项目：三周搭建团队知识库]]。它把需求、计划、周会、复盘与学习记录串在一起，展示知识库如何从零散笔记长成可被检索、可被学习的内容资产。

## 开始前的小清单

```kiwi-task-progress
{"label":"上手检查","showCount":true,"showPercent":true,"color":"violet","bind":"next"}
```

- [ ] 我已经浏览完欢迎页
- [ ] 我完成了一次 Wiki 编译
- [ ] 我在图谱里找到了一个孤立节点
- [ ] 我完成了一次复习

> 提示：本库的学习画像已经预置了部分掌握度，你可以直接体验复习队列与仿真考试，也可以重置学习数据后从头开始。
""",
    tags=("start",),
    wiki_slug="kiwi",
    minutes=0,
)

add_note(
    "quickstart",
    "一分钟上手",
    "start",
    """
# 一分钟上手

这条路线覆盖「记下来 → 连起来 → 编译 → 学习」四步。每一步都能在本库中找到完整示例。

## 1. 记下来

在左侧目录点击「+」新建文档，输入标题后直接写作。输入 `/` 打开块命令，可以插入标题、任务列表、表格、代码块、图片与附件。

> 试一试：在下一行输入 `/table`，插入一张 3×3 的表格。

## 2. 连起来

输入 `@` 从下拉列表选择一篇笔记或 Wiki 页面。引用按 ID 保存，目标改名后仍然有效；保存后，被引用页面的「反向链接」会出现本文。示例见 [[双向链接与反向链接]]。

## 3. 编译成 Wiki

打开导入的原始资料，在条目菜单选择「编译 Wiki」。系统会把资料整理成概念页，并建立引用关系。编译完成后：

- 在「Wiki」页看到页面网络；
- 在「知识图谱」看到节点与边；
- 在「学习」中看到可学习的知识点。

## 4. 学习与复习

进入「学习」→ 选择模式 → 完成练习。答错或不确定的知识点会进入复习队列，按间隔重复安排下一次出现。

## 一页检查清单

```kiwi-task-progress
{"label":"上手进度","showCount":true,"showPercent":true,"color":"indigo","bind":"next"}
```

- [x] 新建并保存一篇文档
- [ ] 插入一个表格和一张图片
- [ ] 用 `@` 提及建立一条双向链接
- [ ] 切换一次画布主题
- [ ] 在数据表里新建一行
- [ ] 编译一次 Wiki
- [ ] 在星图上悬停一个节点
- [ ] 完成一次五题练习
- [ ] 完成一次仿真考试

下一步：[[界面地图]]
""",
    tags=("start", "notes"),
    wiki_slug="notes-workspace",
    minutes=6,
)

add_note(
    "map",
    "界面地图",
    "start",
    """
# 界面地图

Kiwi 的导航按「输入 → 整理 → 理解 → 掌握」组织。第一次使用时，可以按下面的地图逐项体验。

| 导航 | 你在这里做什么 | 关键动作 |
|---|---|---|
| 知识库 | 切换、创建、隐藏与还原知识库 | 内置库删除后可还原 |
| 笔记 | 多文档目录树 + 正文编辑 | 文档 / 画布 / 数据表 / Notebook / 导入 / 外链 |
| Wiki | 浏览编译后的页面网络 | 搜索、反向链接、素材溯源 |
| 图谱 | 查看笔记与 Wiki 的关系 | 精要 / 完整、聚焦、掌握度模式 |
| 学习 | 练习、复习、仿真考试 | 画像、计划、错题与批注 |
| 问答 | 基于知识库内容提问 | 回答带引用来源 |
| 设置 | 模型、Embedding、Wiki Schema | 修改前先阅读说明 |

## 输入与整理

- 文档与画布：[[文档编辑与块命令]]、[[画布：把关系画出来]]
- 结构与数据：[[数据表示例 · 功能体验清单]]、[[Notebook 示例 · 学习记录分析]]
- 资料进入系统：[[导入示例 · Kiwi 功能速查表]]、[[外链示例 · AntV G6 文档]]

## 理解与掌握

- 页面网络：[[Wiki 编译：从笔记长出页面]]
- 关系可视化：[[知识图谱：星图怎么读]]
- 学习闭环：[[学习模式：把 Wiki 变成课程]]、[[复习与仿真考试]]

> 小技巧：在任何页面按 `Ctrl / ⌘ + K` 打开全局搜索，输入标题即可跳转。
""",
    tags=("start",),
    minutes=9,
)

add_note(
    "editor",
    "文档编辑与块命令",
    "workspace",
    """
# 文档编辑与块命令

Kiwi 的编辑器以 Markdown 为唯一事实来源，同时提供接近 Notion 的块编辑体验。切换「编辑 / 阅读」不会丢失内容，导出时也始终得到干净的 Markdown。

## 三种操作方式

1. **直接输入 Markdown**：`##` 标题、`-` 列表、`>` 引用、`**加粗**`；
2. **斜杠命令**：在空行输入 `/`，选择要插入的块；
3. **选中文字后的气泡菜单**：加粗、斜体、链接、高亮、行内代码。

## 常用斜杠命令

| 命令 | 作用 |
|---|---|
| `/h1` `/h2` `/h3` | 插入标题 |
| `/todo` | 插入任务清单 |
| `/table` | 插入表格 |
| `/code` | 插入代码块（带语法高亮） |
| `/image` | 上传图片 |
| `/attachment` | 上传附件并插入下载链接 |
| `/quote` | 插入引用 |
| `/divider` | 插入分割线 |
| `/progress` | 插入待办进度，自动绑定附近的清单 |

工具栏「+ → 扩展组件」提供同一批块；待办进度插入后，点击卡片右上角的齿轮可以修改标题、配色、显示项与绑定方向。

## 任务与表格示例

```kiwi-task-progress
{"label":"编辑功能体验","showCount":true,"showPercent":true,"color":"blue","bind":"next"}
```

- [x] 能新建文档
- [x] 能插入表格
- [ ] 把下面的表格改成自己的功能清单

| 功能 | 使用频率 | 备注 |
|---|---|---|
| Wiki 编译 | 每周 | 资料整理后执行 |
| 复习队列 | 每天 | 通勤时用手机完成 |
| 仿真考试 | 每两周 | 检查整体掌握度 |

## 代码块示例

```python
def review_interval(repetitions: int, ease: float = 2.5) -> float:
    \"\"\"简化版间隔重复：首次 1 天，之后按难度系数增长。\"\"\"
    if repetitions <= 0:
        return 1.0
    return round(ease ** (repetitions - 1), 1)
```

## 图片示例

![Kiwi 功能地图](/media/__KB_ID__/kiwi-feature-map.svg)

> 图片会随笔记一起上传到当前知识库的媒体目录。删除笔记时，正文中的引用会保留但资源仍可通过附件列表管理。

继续阅读：[[双向链接与反向链接]]
""",
    tags=("notes", "editor"),
    wiki_slug="notes-workspace",
    minutes=14,
)

add_note(
    "links",
    "双向链接与反向链接",
    "workspace",
    """
# 双向链接与反向链接

单个知识库的价值取决于连接，而不是条目数量。Kiwi 统一使用 `@` 提及建立文档之间的连接，连接结果会进入知识图谱。

## 推荐写法：@ 提及

1. 在正文输入 `@`；
2. 从下拉列表选择一篇笔记或 Wiki 页面；
3. 选择展示方式：提及 / 标题链接 / 内容卡片 / 嵌入。

引用按 ID 保存：目标笔记改名后，链接仍然有效。旧笔记中已有的 `[[标题]]` 写法仍会在保存时兼容解析，但新内容建议统一使用 `@`。

> 示例：本文引用了 [[文档编辑与块命令]] 和 [[知识图谱：星图怎么读]]。打开这两篇笔记，在右侧「信息 → 反向链接」面板中可以看到本文。

## 反向链接面板

反向链接不占用正文空间，统一显示在右侧「信息」面板。它不是手动维护的索引，而是正文解析的结果：

1. 保存笔记时解析 `@` 提及（兼容旧格式 `[[标题]]`）；
2. 更新笔记之间的有向边；
3. 在图谱中显示为「笔记双向链接」；
4. Wiki 页面侧的引用会聚合为「笔记关联 Wiki」。

## 命名与迁移

`@` 提及不依赖标题。目标改名后引用保持有效；只有文字链接或旧格式 `[[标题]]` 需要手动更新。

## 一个练习

1. 新建一篇笔记，标题写「我的学习清单」；
2. 在正文输入 `@`，选择「复习与仿真考试」；
3. 保存后打开 [[复习与仿真考试]]，在右侧「信息」面板查看反向链接；
4. 打开知识图谱，勾选「包含笔记节点」，找到新增的边。
""",
    tags=("notes",),
    wiki_slug="bidirectional-links",
    minutes=20,
)

add_note(
    "canvas-guide",
    "画布：把关系画出来",
    "workspace",
    """
# 画布：把关系画出来

有些知识不适合写成段落：架构、流程、时序、思维导图。画布提供无限画布、工程图形状与智能连接线，让关系一眼可见。

## 基础操作

- **平移**：拖拽空白区域；**缩放**：滚轮或触控板；
- **创建节点**：左侧图形库选择矩形、圆角、椭圆、菱形、便签、文本、UML、表格、网络设备；
- **连线**：从节点边缘拖出连接线，靠近另一个节点时会自动吸附到最近的锚点；
- **对齐**：拖动时出现对齐辅助线，按住 `Shift` 可锁定水平或垂直；
- **主题**：工程、蓝图、纸张、深夜四种主题，随时切换；
- **模板**：内置流程图、架构图、时序图、思维导图等模板，创建时可一键套用。

## 两个可直接打开的示例

- [[画布示例 · Kiwi 功能全景]]：用中心辐射结构介绍系统模块；
- [[画布示例 · 学习闭环]]：用流程与判定节点展示学习闭环。

## 适合画什么

| 场景 | 推荐结构 | 示例 |
|---|---|---|
| 系统边界 | 分层架构图 | 功能全景 |
| 操作流程 | 流程图 / 状态机 | 学习闭环 |
| 讨论提纲 | 思维导图 | 主题拆解 |
| 接口时序 | 时序图 | 请求与回调 |

> 画布内容保存在笔记的 `props_json.canvas_doc` 中，跟随知识库导出；不依赖外部白板服务。
""",
    tags=("canvas",),
    wiki_slug="canvas",
    minutes=27,
)

add_note(
    "db-guide",
    "数据表示例 · 功能体验清单",
    "workspace",
    """
# 数据表示例 · 功能体验清单

这张数据表用来跟踪「哪些功能已经体验过」。同一批行可以在四种视图之间切换，不需要复制数据。

## 试试这些操作

1. 在「表格」视图修改一行状态；
2. 切到「按状态」看板，把卡片从「未体验」拖到「进行中」；
3. 切到「功能卡片」画册，查看按标题生成的卡片；
4. 切到「体验日历」，按体验日期查看安排。

## 字段说明

- **功能**：主字段，用于卡片标题；
- **模块**：单选，用于看板分组；
- **状态**：未体验 / 进行中 / 已掌握；
- **优先级**：核心 / 进阶 / 可选；
- **体验日期**：日历视图使用；
- **熟练度**：1–5 星；
- **已掌握**：复选框，可配合筛选；
- **备注**：长文本，记录操作路径与坑点。

> 数据表不是电子表格：每一行是结构化记录，字段类型会被校验，适合做任务、台账、术语表与内容清单。
""",
    tags=("database",),
    wiki_slug="database-views",
    minutes=34,
    kind="database",
    props={},
)

add_note(
    "nb-demo",
    "Notebook 示例 · 学习记录分析",
    "workspace",
    """
# Notebook 示例 · 学习记录分析
""",
    tags=("notebook", "study"),
    wiki_slug="notebook",
    kind="notebook",
    minutes=41,
)

add_note(
    "import-demo",
    "导入示例 · Kiwi 功能速查表",
    "workspace",
    """
# Kiwi 功能速查表

## 1. 输入

- 新建文档：左侧目录「+」→ 文档
- 导入文件：支持 Markdown、PDF、DOCX、TXT、HTML
- 外链抓取：粘贴 URL，自动提取正文
- 快速记录：收件箱适合先记后整理

## 2. 整理

- 目录树：拖拽排序、移动分组
- 标签：跨目录聚合，可在图谱中作为筛选依据
- 模板：预填标题、正文、标签
- 数据表：表格 / 看板 / 画册 / 日历
- 画布：工程图、流程图、思维导图

## 3. 理解

- Wiki 编译：资料 → 概念页 + 引用关系
- 双向链接：`[[标题]]` 与 @ 提及
- 反向链接：查看谁引用了当前页面
- 知识图谱：精要 / 完整、聚焦、掌握度
- 问答：基于检索结果回答并标注来源

## 4. 掌握

- 学习画像：目标、基础、每日时长
- 渐进训练：一题一练，即时反馈
- 复习队列：间隔重复，到期提醒
- 仿真考试：整卷计时、自动评分
- 学习批注：个人理解，不写回 Wiki

## 5. 推荐节奏

| 周期 | 动作 |
|---|---|
| 每天 | 清空收件箱；完成到期复习 |
| 每周 | 导入一批资料；编译 Wiki；整理标签 |
| 每两周 | 一次仿真考试；复盘薄弱点 |
| 每月 | 清理孤立页面；更新模板与数据表 |
""",
    tags=("import", "start"),
    wiki_slug="import-pipeline",
    kind="import",
    source_key="cheatsheet",
    minutes=48,
)

add_note(
    "link-demo",
    "外链示例 · AntV G6 文档",
    "workspace",
    """
# AntV G6 图形引擎

AntV G6 是蚂蚁集团开源的图可视化引擎，适合构建关系图、知识图谱与流程图。Kiwi 的知识图谱渲染基于 G6 v5 的 Canvas 渲染器与力导向布局。

## 关键能力

- **图元素**：节点、边、组合（Combo）；
- **布局**：力导向、层次、环形、网格等；
- **交互**：缩放、拖拽、悬停、选中、聚焦；
- **插件**：Tooltip、Minimap、Grid、History 等；
- **主题与样式**：支持基于状态（state）的动态样式。

## 为什么在 Kiwi 里值得了解

1. 图不是一张静态图片，节点可以点击、悬停和筛选；
2. 力导向布局让关系疏密自然呈现，避免手工排版；
3. 状态机制让「掌握度 / 选中 / 悬停」可以叠加表达。

> 本文由外链抓取生成。打开右侧「来源」，可以回到原始网页；在笔记中继续编辑不会影响远端页面。

延伸阅读：[[知识图谱：星图怎么读]]
""",
    tags=("link", "graph"),
    wiki_slug="link-notes",
    kind="link",
    props={
        "link": {
            "url": "https://g6.antv.antgroup.com/manual/introduction",
            "site": "AntV",
            "excerpt": "G6 是一个图可视化引擎。它提供了图的绘制、布局、分析、交互、动画等图可视化的基础能力。",
            "favicon": "https://g6.antv.antgroup.com/favicon.ico",
            "final_url": "https://g6.antv.antgroup.com/manual/introduction",
            "fetched_at": ts(52),
            "fetch_error": None,
            "fetch_status": "ok",
        }
    },
    minutes=55,
)

add_note(
    "wiki-compile",
    "Wiki 编译：从笔记长出页面",
    "wiki",
    """
# Wiki 编译：从笔记长出页面

Wiki 不是另一套手写文档，而是对已有资料的再组织。编译器会阅读导入的素材，抽取概念、实体与指标，生成带来源的页面，并维护页面之间的引用关系。

## 编译做了什么

1. **切分与理解**：按标题层级切块，识别主题与定义；
2. **生成页面**：为每个概念生成标题、摘要、要点与关系；
3. **建立引用**：正文中的 `[[页面]]` 会转成 Wiki 链接；
4. **记录来源**：页面保存 `compiled_from_source_ids`，可追溯到原始素材；
5. **增量更新**：素材变化时只重编译受影响的页面；人工编辑过的页面默认受保护。

## 页面类型

| 类型 | 用途 | 示例 |
|---|---|---|
| 实体 | 具体系统、组织、产品 | Kiwi |
| 概念 | 术语、方法、指标 | 间隔重复 |
| 摘要 | 对一份素材的浓缩 | Kiwi 功能速查表 |
| 综合 | 跨多份素材的主题总结 | 如何完成一次主题学习 |

## 人工编辑与保护

点击页面右上角「编辑」可以直接改写正文。保存后页面进入「人工保护」状态：后续增量编译不会覆盖它，但会提示「源素材已更新」。

## 溯源与逆向跳转

页面右侧「来源」面板列出编译素材。由导入生成的素材会显示「来源笔记」，点击即可跳回原始笔记，对照上下文或继续编辑。

> 编译质量取决于素材质量。先用 [[导入示例 · Kiwi 功能速查表]] 体验一次完整流程，再阅读 [[知识图谱：星图怎么读]] 看看页面如何连接。
""",
    tags=("wiki", "import"),
    wiki_slug="wiki-compile",
    minutes=62,
)

add_note(
    "graph-guide",
    "知识图谱：星图怎么读",
    "wiki",
    """
# 知识图谱：星图怎么读

图谱把笔记、Wiki 页面与它们之间的关系画成一张可探索的星图。节点是知识，连线是关系，亮度是掌握度。

## 节点类型

| 颜色 / 形状 | 类型 | 含义 |
|---|---|---|
| 靛蓝 | 实体 | Wiki 中的具体对象 |
| 天蓝 | 概念 | Wiki 中的术语与方法 |
| 绿色 | 摘要 | 对素材的浓缩页 |
| 琥珀 | 综合 | 跨素材的主题总结 |
| 灰白 | 笔记 | 工作区中的文档、画布等 |
| 粉色 | Wiki | 未归类的页面 |

## 边的类型

- **引用**：Wiki 页面之间的 `[[...]]` 关系；
- **相关**：系统按共同引用补充的弱关系，仅在完整模式显示；
- **笔记双向链接**：笔记正文中的 @ 提及；
- **笔记关联 Wiki**：笔记 props 中记录的 Wiki 页面；
- **矛盾标记**：编译时发现的内容冲突。

## 三种读法

1. **精要模式**：隐藏弱关系、合并重复边，只看骨架，默认使用；
2. **完整模式**：显示全部关系，适合排查孤立页面；
3. **掌握度模式**：节点亮度对应掌握度，暗星表示尚未掌握，优先学习。

## 交互

- 悬停节点：高亮一度邻居，其余变暗；移出后自动恢复；
- 单击节点：打开详情或跳转；
- 筛选：包含笔记节点、仅看当前选中节点的邻域；
- 刷新布局：重新计算力导向布局，不改变缩放比例。

> 图谱不是装饰。每周看一次暗星与孤立点，就能找到知识库的结构性缺口。
""",
    tags=("graph", "wiki"),
    wiki_slug="knowledge-graph",
    minutes=69,
)

add_note(
    "tags-templates",
    "标签与模板：让整理可复用",
    "wiki",
    """
# 标签与模板：让整理可复用

目录解决「放在哪里」，标签解决「属于什么」，模板解决「每次怎么开始」。

## 标签

- 标签是知识库级维度，可以跨目录聚合；
- 一篇笔记可以有多个标签，标签本身可以分组；
- 常用标签：入门、笔记、画布、数据表、Notebook、导入、Wiki、图谱、学习、复习；
- 建议控制在 15 个以内，超过后先合并同义标签。

## 模板

模板保存标题格式、正文骨架、默认标签与属性。创建笔记时选择模板，系统会自动填充并替换 `{占位符}`。

本库内置两个模板：

1. **功能体验记录**：记录操作路径、结果与改进点；
2. **每周学习复盘**：汇总学习时长、正确率与下周计划。

## 一个可复用的整理流程

1. 新资料先进入「收件箱」，只打一个标签；
2. 每周固定时间把收件箱清空，移入正式目录；
3. 结构稳定后，把重复出现的写法沉淀为模板；
4. 模板更新后，旧笔记不自动改写，但新建笔记立即受益。

> 标签与模板都属于知识库本身，切换知识库时不会混用。参见 [[Wiki 编译：从笔记长出页面]]。
""",
    tags=("template", "notes"),
    wiki_slug="tags-templates",
    minutes=76,
)

add_note(
    "study-mode",
    "学习模式：把 Wiki 变成课程",
    "study",
    """
# 学习模式：把 Wiki 变成课程

Wiki 解决「内容在哪里」，学习模式解决「我是否真的掌握」。开启学习模式后，每个 Wiki 页面都会成为可出题、可评分、可复习的知识点。

## 第一次进入

1. 设置学习目标：领域学习 / 考试备考 / 项目速成；
2. 选择基础水平与每日可用时长；
3. 确认薄弱领域，系统生成学习画像；
4. 系统按画像安排每日任务与建议模式。

## 三种练习方式

| 方式 | 适合场景 | 反馈 |
|---|---|---|
| 渐进训练 | 日常学习、专项补弱 | 每题即时反馈与解析 |
| 复习队列 | 到期知识点的巩固 | 按间隔重复安排 |
| 仿真考试 | 阶段性检验 | 整卷计时、统一评分 |

## 智能出题

题目来自 Wiki 页面内容，并按题型生成：单选、判断、简答、案例分析。每道题都带引用页面、难度与解析；批注属于个人学习数据，不会写回 Wiki。

## 掌握度如何变化

答对会提高掌握度并延长复习间隔；答错会降低掌握度并缩短间隔。连续多次正确后，知识点从「学习中」进入「已掌握」。

> 建议每天 20–30 分钟：先清复习队列，再做一轮渐进训练；每两周安排一次仿真考试。
""",
    tags=("study",),
    wiki_slug="study-mode",
    minutes=83,
)

add_note(
    "review-exam",
    "复习与仿真考试",
    "study",
    """
# 复习与仿真考试

学习的最后一步不是「看完」，而是「在该想起来的时候想起来」。

## 复习队列

- 每个知识点有独立的复习状态：难度系数、间隔天数、连续正确次数；
- 到期知识点会出现在复习队列，逾期会标记为「已到期」；
- 答对延长间隔，答错缩短间隔并重新进入近期队列；
- 队列按到期时间排序，不按创建时间排序。

## 仿真考试

1. 选择题型模板与时长；
2. 系统按知识覆盖与难度分布组卷；
3. 作答过程中切出学习模式会自动暂停计时；
4. 交卷后自动评分：客观题按答案，主观题按评分维度；
5. 生成成绩单：总分、分项得分、薄弱知识点与时间分析。

## 成绩怎么看

| 指标 | 含义 | 建议 |
|---|---|---|
| 总分 | 整卷得分率 | 低于合格线先补基础 |
| 分项得分 | 各题型表现 | 找到失分集中区 |
| 薄弱知识点 | 得分率低的知识点 | 回到 Wiki 重新学习 |
| 时间分析 | 各题型用时 | 调整答题节奏 |

## 一个闭环样例

1. 复习队列中有 3 个到期知识点；
2. 完成渐进训练，正确率 67%；
3. 两天后做一场仿真考试，总分 82.5；
4. 成绩单指出「间隔重复」薄弱；
5. 回到 Wiki 重读该页，并加入下一次复习。

> 复习与考试的数据只属于当前知识库的学习画像，不影响 Wiki 正文。
""",
    tags=("study", "review"),
    wiki_slug="spaced-repetition",
    minutes=90,
)

add_note(
    "project",
    "示例项目：三周搭建团队知识库",
    "project",
    """
# 示例项目：三周搭建团队知识库

这是一个虚构但完整的团队场景：五人产品团队要在三周内，把散落在聊天记录、文档和网页里的资料，整理成一套新人可以自学、老成员可以检索的知识库。

## 目标

- 新人入职两周内能独立完成资料整理与基础学习；
- 核心概念有统一定义，不再出现「同名不同义」；
- 每周复盘一次知识库健康度，持续清理孤立页面。

## 分工

| 角色 | 负责人 | 职责 |
|---|---|---|
| 项目负责人 | 林澜 | 范围、节奏、验收 |
| 内容整理 | 周野 | 导入、去重、分类 |
| Wiki 维护 | 陈默 | 编译、人工校对、引用 |
| 学习设计 | 许澄 | 画像、题目、复习计划 |
| 工具支持 | 顾言 | 模板、数据表、自动化 |

## 三周节奏

| 周次 | 主题 | 关键动作 | 产出 |
|---|---|---|---|
| 第 1 周 | 收集与归类 | 导入资料、建立目录与标签 | 素材清单、目录树 |
| 第 2 周 | 编译与连接 | 编译 Wiki、补双向链接、清理孤立页 | Wiki 页面网络 |
| 第 3 周 | 学习与验收 | 学习画像、练习、仿真考试、复盘 | 学习报告、验收结论 |

## 本周正在做的事

- 任务与里程碑：[[示例项目 · 任务与里程碑]]
- 周会纪要：[[示例项目 · 周会纪要]]
- 健康度复盘：[[示例项目 · 知识库健康度复盘]]

## 验收标准

- [ ] 核心概念页覆盖率 ≥ 90%
- [ ] 孤立页面占比 < 5%
- [ ] 新人完成一次仿真考试且总分 ≥ 80
- [ ] 每位成员能独立完成导入 → 编译 → 学习闭环

> 这个项目的价值不在文档数量，而在于「可检索、可追溯、可学习」。继续阅读 [[示例项目 · 知识库健康度复盘]]。
""",
    tags=("project", "start", "import"),
    kind="import",
    source_key="project-brief",
    wiki_slug="team-kb-in-three-weeks",
    minutes=97,
)

add_note(
    "weekly-note",
    "示例项目 · 周会纪要",
    "project",
    """
# 第 2 周项目周会纪要

> 日期：2026-10-16 ｜ 主持：林澜 ｜ 参与：周野、陈默、许澄、顾言

## 一、上周行动项回顾

- [x] 完成 12 份资料的导入与去重（周野）
- [x] 建立 6 个一级目录与 14 个标签（顾言）
- [x] 输出首版 Wiki Schema（陈默）
- [ ] 补齐 5 个概念页的引用（陈默，延期到本周三）

## 二、本周进展

| 工作项 | 计划 | 实际 | 偏差说明 |
|---|---|---|---|
| Wiki 编译 | 18 页 | 19 页 | 多出一页「学习画像」 |
| 双向链接 | 30 条 | 41 条 | 编译自动补链 |
| 学习画像 | 1 份 | 1 份 | 已进入练习阶段 |
| 数据表模板 | 2 个 | 2 个 | 任务板、术语表 |

## 三、风险与问题

| 编号 | 描述 | 等级 | 责任人 | 截止时间 |
|---|---|---|---|---|
| R1 | 两份旧文档对「精要视图」定义不一致 | 中 | 陈默 | 10-19 |
| R2 | 新人反馈图谱节点太多，不知道从哪看 | 中 | 顾言 | 10-20 |
| R3 | 仿真考试主观题评分标准待确认 | 低 | 许澄 | 10-22 |

## 四、需要决策的事项

1. 是否将「相关」边默认隐藏在精要视图（已确认：是）；
2. 新人培训以 Wiki 阅读为主，还是直接进入学习模式（结论：先读后练）。

## 五、下周计划

- 完成第二轮学习练习与一次仿真考试；
- 清理孤立页面，目标占比低于 5%；
- 输出三周项目复盘。
""",
    tags=("project",),
    minutes=104,
)

add_note(
    "health",
    "示例项目 · 知识库健康度复盘",
    "project",
    """
# 知识库健康度复盘

> 统计时间：2026-10-18 ｜ 数据来源：Wiki 列表、图谱完整模式、学习画像

## 本周指标

| 指标 | 数值 | 目标 | 判断 |
|---|---|---|---|
| 笔记数 | 23 | — | 稳定 |
| Wiki 页面 | 19 | 18 | 达标 |
| 双向链接 | 41 | 30 | 达标 |
| 孤立页面占比 | 10.5% | < 5% | 未达标 |
| 核心概念覆盖率 | 86% | ≥ 90% | 接近 |
| 到期复习 | 3 | 0 | 需处理 |
| 仿真考试总分 | 82.5 | ≥ 80 | 达标 |

## 发现

1. **两个孤立页面**：「Notebook」与「标签与模板」只被目录引用，没有正文链路；
2. **一个命名冲突**：「精要视图」在不同页面分别指图谱与 Wiki 列表；
3. **复习积压**：过去一周有 3 个知识点到期未复习，集中在「间隔重复」；
4. **考试薄弱项**：判断题正确率仅 50%，说明定义边界还不够清晰。

## 行动

- [ ] 为两个孤立页面补充双向链接（陈默）
- [ ] 统一「精要视图」术语并更新两处正文（周野）
- [ ] 本周内清空到期复习（全员）
- [ ] 针对「间隔重复」增加 5 道判断题（许澄）

## 结论

知识库的健康度不等于内容数量。真正需要持续维护的是：**连接是否完整、定义是否一致、学习是否发生**。下一轮复盘将对比本周行动项的完成情况。
""",
    tags=("project", "review"),
    minutes=111,
)

add_note(
    "task-db",
    "示例项目 · 任务与里程碑",
    "project",
    """
# 示例项目 · 任务与里程碑
""",
    tags=("project", "database"),
    kind="database",
    minutes=118,
)

add_note(
    "inbox",
    "收件箱 · 灵感与待办",
    "inbox",
    """
# 收件箱 · 灵感与待办

这里是一个「先记下来，稍后整理」的缓冲区。每周清空一次：能归类就归类，不能归类就先合并。

## 本周捕获

- 试试用画布的蓝图主题画一次接口时序；
- 数据表能不能用来管理模板版本？先建一个实验表；
- 给「间隔重复」页面补一张遗忘曲线示意图；
- 仿真考试的判断题需要更多边界案例；
- 把新人常问的 10 个问题整理成一页 FAQ。

## 处理规则

1. 两分钟内能做完的，立刻做；
2. 需要资料的，转成任务并标注负责人；
3. 暂时不做的，保留标签「收件箱」；
4. 每周五复盘，删除已经过期的想法。

> 收件箱不是长期仓库。它的唯一目标是让大脑暂时放下，同时保证不丢失。
""",
    tags=("notes",),
    minutes=125,
)

# 画布示例笔记
add_note(
    "canvas-overview",
    "画布示例 · Kiwi 功能全景",
    "workspace",
    "",
    kind="canvas",
    tags=("canvas",),
    sort=2,
    minutes=132,
)
add_note(
    "canvas-loop",
    "画布示例 · 学习闭环",
    "workspace",
    "",
    kind="canvas",
    tags=("canvas", "study"),
    sort=3,
    minutes=139,
)

# 画布 props 在下方统一注入
CANVAS_DOCS: dict[str, dict] = {}
NOTEBOOK_DOCS: dict[str, dict] = {}
DATABASES: dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# 画布：功能全景
# --------------------------------------------------------------------------- #

CANVAS_DOCS["canvas-overview"] = {
    "version": 1,
    "theme": "engineering",
    "grid": True,
    "snap": True,
    "viewport": {"x": 30, "y": 40, "zoom": 0.78},
    "nodes": [
        {
            "id": "c-title",
            "shape": "text",
            "x": 40,
            "y": 20,
            "w": 660,
            "h": 40,
            "text": "Kiwi 功能全景",
            "fontSize": 24,
            "bold": True,
            "align": "left",
        },
        {
            "id": "c-sub",
            "shape": "text",
            "x": 40,
            "y": 60,
            "w": 720,
            "h": 28,
            "text": "从输入、整理到理解与掌握：六条能力线围绕同一个知识库",
            "fontSize": 13,
            "align": "left",
        },
        {
            "id": "c-center",
            "shape": "round",
            "x": 470,
            "y": 330,
            "w": 260,
            "h": 100,
            "text": "Kiwi\n知识工作台",
            "fontSize": 18,
            "bold": True,
            "tone": "accent",
            "align": "center",
        },
        {
            "id": "c-notes",
            "shape": "rect",
            "x": 110,
            "y": 150,
            "w": 220,
            "h": 82,
            "text": "笔记工作区\n文档 · 双向链接 · 模板",
            "fontSize": 14,
            "tone": "neutral",
        },
        {
            "id": "c-canvas",
            "shape": "rect",
            "x": 110,
            "y": 330,
            "w": 200,
            "h": 82,
            "text": "画布\n工程图 · 思维导图",
            "fontSize": 14,
            "tone": "green",
        },
        {
            "id": "c-db",
            "shape": "rect",
            "x": 130,
            "y": 520,
            "w": 200,
            "h": 82,
            "text": "数据表\n表格 / 看板 / 画册 / 日历",
            "fontSize": 14,
            "tone": "violet",
        },
        {
            "id": "c-wiki",
            "shape": "round",
            "x": 880,
            "y": 150,
            "w": 220,
            "h": 82,
            "text": "Wiki\n编译 · 溯源 · 反向链接",
            "fontSize": 14,
            "tone": "accent",
        },
        {
            "id": "c-graph",
            "shape": "round",
            "x": 900,
            "y": 330,
            "w": 200,
            "h": 82,
            "text": "知识图谱\n关系 · 掌握度星图",
            "fontSize": 14,
            "tone": "amber",
        },
        {
            "id": "c-study",
            "shape": "round",
            "x": 880,
            "y": 520,
            "w": 220,
            "h": 82,
            "text": "学习模式\n练习 · 复习 · 仿真考试",
            "fontSize": 14,
            "tone": "rose",
        },
        {
            "id": "c-notebook",
            "shape": "sticky",
            "x": 420,
            "y": 640,
            "w": 220,
            "h": 92,
            "text": "Notebook\n代码、输出与结论同页",
            "fontSize": 13,
            "tone": "amber",
        },
    ],
    "edges": [
        {"id": "ce1", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "c-notes"}, "arrow": "none", "curve": "bezier", "label": "写作"},
        {"id": "ce2", "from": {"x": 0, "y": 0, "side": "left", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "right", "nodeId": "c-canvas"}, "arrow": "none", "curve": "bezier", "label": "画出来"},
        {"id": "ce3", "from": {"x": 0, "y": 0, "side": "bottom", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "top", "nodeId": "c-notebook"}, "arrow": "none", "curve": "bezier", "label": "分析"},
        {"id": "ce4", "from": {"x": 0, "y": 0, "side": "left", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "right", "nodeId": "c-db"}, "arrow": "none", "curve": "bezier", "label": "结构化"},
        {"id": "ce5", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "c-wiki"}, "arrow": "none", "curve": "bezier", "label": "编译"},
        {"id": "ce6", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "c-graph"}, "arrow": "none", "curve": "bezier", "label": "连接"},
        {"id": "ce7", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "c-center"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "c-study"}, "arrow": "none", "curve": "bezier", "label": "掌握"},
        {"id": "ce8", "from": {"x": 0, "y": 0, "side": "bottom", "nodeId": "c-wiki"}, "to": {"x": 0, "y": 0, "side": "top", "nodeId": "c-graph"}, "arrow": "end", "curve": "orthogonal", "label": "页面与边"},
        {"id": "ce9", "from": {"x": 0, "y": 0, "side": "bottom", "nodeId": "c-graph"}, "to": {"x": 0, "y": 0, "side": "top", "nodeId": "c-study"}, "arrow": "end", "curve": "orthogonal", "label": "知识点"},
    ],
}

CANVAS_DOCS["canvas-loop"] = {
    "version": 1,
    "theme": "blueprint",
    "grid": True,
    "snap": True,
    "viewport": {"x": 40, "y": 50, "zoom": 0.75},
    "nodes": [
        {
            "id": "f-title",
            "shape": "text",
            "x": 40,
            "y": 24,
            "w": 760,
            "h": 40,
            "text": "学习闭环：从资料到掌握",
            "fontSize": 24,
            "bold": True,
            "align": "left",
        },
        {
            "id": "f-sub",
            "shape": "text",
            "x": 40,
            "y": 64,
            "w": 820,
            "h": 28,
            "text": "每一次循环都以「薄弱点」为输入，而不是从头再来",
            "fontSize": 13,
            "align": "left",
        },
        {
            "id": "f-capture",
            "shape": "round",
            "x": 60,
            "y": 180,
            "w": 190,
            "h": 84,
            "text": "收集资料\n导入 / 外链",
            "fontSize": 14,
            "tone": "neutral",
        },
        {
            "id": "f-notes",
            "shape": "rect",
            "x": 320,
            "y": 180,
            "w": 190,
            "h": 84,
            "text": "笔记整理\n目录 · 标签 · 模板",
            "fontSize": 14,
            "tone": "neutral",
        },
        {
            "id": "f-compile",
            "shape": "rect",
            "x": 580,
            "y": 180,
            "w": 190,
            "h": 84,
            "text": "Wiki 编译\n概念 · 来源",
            "fontSize": 14,
            "tone": "accent",
        },
        {
            "id": "f-graph",
            "shape": "rect",
            "x": 840,
            "y": 180,
            "w": 190,
            "h": 84,
            "text": "知识图谱\n关系 · 暗星",
            "fontSize": 14,
            "tone": "accent",
        },
        {
            "id": "f-learn",
            "shape": "rect",
            "x": 840,
            "y": 360,
            "w": 190,
            "h": 84,
            "text": "渐进训练\n即时反馈",
            "fontSize": 14,
            "tone": "green",
        },
        {
            "id": "f-review",
            "shape": "rect",
            "x": 580,
            "y": 360,
            "w": 190,
            "h": 84,
            "text": "复习队列\n间隔重复",
            "fontSize": 14,
            "tone": "green",
        },
        {
            "id": "f-exam",
            "shape": "rect",
            "x": 320,
            "y": 360,
            "w": 190,
            "h": 84,
            "text": "仿真考试\n成绩单",
            "fontSize": 14,
            "tone": "amber",
        },
        {
            "id": "f-check",
            "shape": "diamond",
            "x": 330,
            "y": 520,
            "w": 170,
            "h": 110,
            "text": "达到目标？",
            "fontSize": 14,
            "tone": "amber",
        },
        {
            "id": "f-weak",
            "shape": "sticky",
            "x": 80,
            "y": 530,
            "w": 190,
            "h": 96,
            "text": "薄弱点\n→ 定向练习\n→ 更新计划",
            "fontSize": 13,
            "tone": "rose",
        },
        {
            "id": "f-done",
            "shape": "round",
            "x": 590,
            "y": 540,
            "w": 180,
            "h": 76,
            "text": "进入下一主题",
            "fontSize": 14,
            "tone": "green",
        },
    ],
    "edges": [
        {"id": "fe1", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "f-capture"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "f-notes"}, "arrow": "end", "curve": "orthogonal", "label": "归入目录"},
        {"id": "fe2", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "f-notes"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "f-compile"}, "arrow": "end", "curve": "orthogonal", "label": "编译"},
        {"id": "fe3", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "f-compile"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "f-graph"}, "arrow": "end", "curve": "orthogonal", "label": "成网"},
        {"id": "fe4", "from": {"x": 0, "y": 0, "side": "bottom", "nodeId": "f-graph"}, "to": {"x": 0, "y": 0, "side": "top", "nodeId": "f-learn"}, "arrow": "end", "curve": "orthogonal", "label": "知识点"},
        {"id": "fe5", "from": {"x": 0, "y": 0, "side": "left", "nodeId": "f-learn"}, "to": {"x": 0, "y": 0, "side": "right", "nodeId": "f-review"}, "arrow": "end", "curve": "straight", "label": "到期"},
        {"id": "fe6", "from": {"x": 0, "y": 0, "side": "left", "nodeId": "f-review"}, "to": {"x": 0, "y": 0, "side": "right", "nodeId": "f-exam"}, "arrow": "end", "curve": "straight", "label": "阶段检验"},
        {"id": "fe7", "from": {"x": 0, "y": 0, "side": "bottom", "nodeId": "f-exam"}, "to": {"x": 0, "y": 0, "side": "top", "nodeId": "f-check"}, "arrow": "end", "curve": "orthogonal", "label": "评分"},
        {"id": "fe8", "from": {"x": 0, "y": 0, "side": "left", "nodeId": "f-check"}, "to": {"x": 0, "y": 0, "side": "right", "nodeId": "f-weak"}, "arrow": "end", "curve": "straight", "label": "否"},
        {"id": "fe9", "from": {"x": 0, "y": 0, "side": "right", "nodeId": "f-check"}, "to": {"x": 0, "y": 0, "side": "bottom", "nodeId": "f-done"}, "arrow": "end", "curve": "straight", "label": "是"},
        {"id": "fe10", "from": {"x": 0, "y": 0, "side": "top", "nodeId": "f-weak"}, "to": {"x": 0, "y": 0, "side": "left", "nodeId": "f-learn"}, "arrow": "end", "curve": "bezier", "label": "回到训练", "dashed": True},
    ],
}

NOTES_BY_KEY = {n["key"]: n for n in NOTES}


# 文档之间的引用统一写成 @ 提及（编辑器持久化格式），避免正文出现原始 [[标题]]。
# 用 split 保留代码段：`[[标题]]` 这类语法说明不应被替换成链接。
_NOTE_TITLE_TO_ID = {note["title"]: note["id"] for note in NOTES}
_NOTE_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")


def _replace_note_wikilinks(text: str) -> str:
    parts = re.split(r"(```[\s\S]*?```|`[^`\n]*`)", text)
    for index in range(0, len(parts), 2):
        def _mention(match: re.Match[str]) -> str:
            title = match.group(1).strip()
            target = _NOTE_TITLE_TO_ID.get(title)
            if target is None:
                return match.group(0)
            return f"[@{title}](kiwi://note/{target})"

        parts[index] = _NOTE_WIKILINK_RE.sub(_mention, parts[index])
    return "".join(parts)


for _note in NOTES:
    _note["body_md"] = _replace_note_wikilinks(_note["body_md"])
    _note["body_md"] = _note["body_md"].replace(
        "双向链接：`[[标题]]` 与 @ 提及", "双向链接：@ 提及笔记与 Wiki"
    )


def db_options(items: list[tuple[str, str, str]]) -> list[dict]:
    return [{"id": key, "name": name, "color": color} for key, name, color in items]


# --------------------------------------------------------------------------- #
# 数据表：功能体验清单
# --------------------------------------------------------------------------- #

EXPERIENCE_FIELDS = [
    {"id": "name", "name": "功能", "type": "text"},
    {
        "id": "module",
        "name": "模块",
        "type": "select",
        "options": db_options(
            [
                ("notes", "笔记", "blue"),
                ("canvas", "画布", "violet"),
                ("database", "数据表", "cyan"),
                ("notebook", "Notebook", "orange"),
                ("import", "导入", "amber"),
                ("wiki", "Wiki", "green"),
                ("graph", "图谱", "rose"),
                ("study", "学习", "green"),
            ]
        ),
    },
    {
        "id": "status",
        "name": "状态",
        "type": "select",
        "options": db_options(
            [("todo", "未体验", "slate"), ("doing", "进行中", "blue"), ("done", "已掌握", "green")]
        ),
    },
    {
        "id": "priority",
        "name": "优先级",
        "type": "select",
        "options": db_options(
            [("core", "核心", "rose"), ("plus", "进阶", "amber"), ("opt", "可选", "slate")]
        ),
    },
    {"id": "date", "name": "体验日期", "type": "date"},
    {"id": "mastered", "name": "已掌握", "type": "checkbox"},
    {"id": "rating", "name": "熟练度", "type": "rating"},
    {"id": "note", "name": "备注", "type": "long_text"},
]

EXP_VIEWS = [
    {
        "id": "table",
        "name": "表格",
        "type": "table",
        "sorts": [],
        "filters": [],
        "row_heights": {},
        "column_widths": {},
        "hidden_fields": ["note"],
    },
    {"id": "kanban", "name": "按状态", "type": "kanban", "group_field": "status", "display_fields": None},
    {"id": "gallery", "name": "功能卡片", "type": "gallery", "cover_field": None, "title_field": "name"},
    {
        "id": "calendar",
        "name": "体验日历",
        "type": "calendar",
        "bar_color": None,
        "end_field": None,
        "date_field": "date",
        "title_field": "name",
    },
]

EXPERIENCE_ROWS = [
    ("块命令与表格", "notes", "done", "core", "2026-10-12", True, 5, "输入 / 后可以直接插入块；表格支持行内编辑。"),
    ("双向链接与反向链接", "notes", "done", "core", "2026-10-12", True, 5, "保存后反向链接面板立即出现引用来源。"),
    ("画布智能粘连", "canvas", "done", "core", "2026-10-13", True, 4, "连接线靠近节点自动吸附，移动节点时连线跟随。"),
    ("画布主题切换", "canvas", "doing", "plus", "2026-10-19", False, 3, "蓝图主题适合流程，工程主题适合架构。"),
    ("数据表看板视图", "database", "done", "core", "2026-10-14", True, 4, "拖动卡片会直接修改分组字段。"),
    ("数据表日历视图", "database", "doing", "plus", "2026-10-20", False, 3, "日期字段使用 YYYY-MM-DD，避免时区偏移。"),
    ("Notebook 执行", "notebook", "doing", "plus", "2026-10-21", False, 3, "pandas 与 matplotlib 可用，输出保存在单元格里。"),
    ("导入 Markdown / PDF", "import", "done", "core", "2026-10-15", True, 4, "重复文件按 sha256 去重，不重复向量化。"),
    ("外链抓取", "import", "done", "plus", "2026-10-15", True, 4, "抓取失败会降级为书签卡片，仍可手动补充。"),
    ("Wiki 编译与溯源", "wiki", "doing", "core", "2026-10-22", False, 3, "人工编辑后进入保护状态，增量编译不覆盖。"),
    ("图谱精要与筛选", "graph", "todo", "core", "2026-10-23", False, 2, "精要模式隐藏相关边，适合日常浏览。"),
    ("复习队列", "study", "todo", "core", "2026-10-24", False, 2, "到期知识点按时间排序，逾期会标红。"),
    ("仿真考试", "study", "todo", "plus", "2026-10-27", False, 1, "45 分钟整卷，交卷后生成成绩单。"),
]

DATABASES["db-guide"] = {
    "name": "功能体验清单",
    "description": "用四种视图跟踪 Kiwi 功能的体验进度。",
    "fields": EXPERIENCE_FIELDS,
    "views": EXP_VIEWS,
    "rows": [
        {
            "name": row[0],
            "module": row[1],
            "status": row[2],
            "priority": row[3],
            "date": row[4],
            "mastered": row[5],
            "rating": row[6],
            "note": row[7],
        }
        for row in EXPERIENCE_ROWS
    ],
}

# --------------------------------------------------------------------------- #
# 数据表：任务与里程碑
# --------------------------------------------------------------------------- #

TASK_FIELDS = [
    {"id": "name", "name": "任务", "type": "text"},
    {
        "id": "owner",
        "name": "负责人",
        "type": "select",
        "options": db_options(
            [
                ("lin", "林澜", "blue"),
                ("zhou", "周野", "green"),
                ("chen", "陈默", "violet"),
                ("xu", "许澄", "amber"),
                ("gu", "顾言", "cyan"),
            ]
        ),
    },
    {
        "id": "status",
        "name": "状态",
        "type": "select",
        "options": db_options(
            [("todo", "待开始", "slate"), ("doing", "进行中", "blue"), ("review", "待验收", "amber"), ("done", "已完成", "green")]
        ),
    },
    {
        "id": "milestone",
        "name": "里程碑",
        "type": "select",
        "options": db_options(
            [("w1", "第 1 周 · 收集", "cyan"), ("w2", "第 2 周 · 编译", "violet"), ("w3", "第 3 周 · 验收", "green")]
        ),
    },
    {"id": "due", "name": "截止日期", "type": "date"},
    {"id": "progress", "name": "进度", "type": "progress"},
    {"id": "note", "name": "说明", "type": "long_text"},
]

TASK_VIEWS = [
    {
        "id": "table",
        "name": "表格",
        "type": "table",
        "sorts": [{"field": "due", "direction": "asc"}],
        "filters": [],
        "row_heights": {},
        "column_widths": {},
        "hidden_fields": ["note"],
    },
    {"id": "kanban", "name": "按状态", "type": "kanban", "group_field": "status", "display_fields": None},
    {"id": "gallery", "name": "任务卡片", "type": "gallery", "cover_field": None, "title_field": "name"},
    {
        "id": "calendar",
        "name": "截止日历",
        "type": "calendar",
        "bar_color": None,
        "end_field": None,
        "date_field": "due",
        "title_field": "name",
    },
]

TASK_ROWS = [
    ("导入 12 份基础资料并去重", "zhou", "done", "w1", "2026-10-10", 100, "含 3 份 PDF、6 份 Markdown、3 个网页。"),
    ("建立目录树与标签体系", "gu", "done", "w1", "2026-10-11", 100, "6 个一级目录、14 个标签。"),
    ("输出首版 Wiki Schema", "chen", "done", "w1", "2026-10-12", 100, "约定页面类型与引用格式。"),
    ("完成第一轮 Wiki 编译", "chen", "done", "w2", "2026-10-15", 100, "19 页，人工校对 6 页。"),
    ("补齐概念页双向链接", "chen", "review", "w2", "2026-10-18", 90, "还剩 2 个孤立页面。"),
    ("制作功能体验数据表", "gu", "done", "w2", "2026-10-16", 100, "四种视图全部可用。"),
    ("搭建学习画像与练习", "xu", "doing", "w3", "2026-10-21", 55, "已完成画像，题目生成中。"),
    ("组织一次仿真考试", "xu", "todo", "w3", "2026-10-24", 0, "目标总分 ≥ 80。"),
    ("知识库健康度复盘", "lin", "todo", "w3", "2026-10-25", 0, "检查孤立页、覆盖率与复习积压。"),
    ("新人上手验收", "lin", "todo", "w3", "2026-10-27", 0, "新人独立完成导入→编译→学习闭环。"),
]

DATABASES["task-db"] = {
    "name": "三周项目任务板",
    "description": "示例项目的任务、负责人、里程碑与截止日期。",
    "fields": TASK_FIELDS,
    "views": TASK_VIEWS,
    "rows": [
        {
            "name": row[0],
            "owner": row[1],
            "status": row[2],
            "milestone": row[3],
            "due": row[4],
            "progress": row[5],
            "note": row[6],
        }
        for row in TASK_ROWS
    ],
}

# --------------------------------------------------------------------------- #
# Notebook：学习记录分析
# --------------------------------------------------------------------------- #

NB_ROWS = [
    ("笔记工作区", 0.86, 12, 11),
    ("双向链接", 0.80, 10, 9),
    ("知识库", 0.78, 9, 8),
    ("Wiki 编译", 0.72, 11, 9),
    ("学习图谱", 0.68, 8, 6),
    ("学习闭环", 0.65, 6, 5),
    ("画布", 0.62, 7, 5),
    ("Notebook", 0.58, 6, 4),
    ("学习模式", 0.57, 9, 6),
    ("数据表视图", 0.54, 7, 4),
    ("间隔重复", 0.40, 8, 4),
    ("导入流水线", 0.34, 6, 3),
    ("仿真考试", 0.31, 5, 2),
]

_accuracy = [round(correct / total * 100) for _, _, total, correct in NB_ROWS]
_avg_mastery = round(sum(row[1] for row in NB_ROWS) / len(NB_ROWS) * 100)
_total_correct = sum(row[3] for row in NB_ROWS)
_total_questions = sum(row[2] for row in NB_ROWS)
_overall_accuracy = round(_total_correct / _total_questions * 100)
_weakest = "、".join(row[0] for row in sorted(NB_ROWS, key=lambda row: row[1])[:3])

NB_STREAM = (
    f"平均掌握度：{_avg_mastery}%\n"
    f"总正确率：{_overall_accuracy}%（{_total_correct}/{_total_questions}）\n"
    f"最薄弱的三个知识点：{_weakest}\n"
)

_header = "".join(f"<th>{name}</th>" for name in ("知识点", "掌握度", "练习题", "答对", "正确率"))
_body = "".join(
    "<tr>"
    f"<td>{name}</td><td>{int(mastery * 100)}%</td>"
    f"<td>{total}</td><td>{correct}</td><td>{accuracy}%</td>"
    "</tr>"
    for (name, mastery, total, correct), accuracy in zip(NB_ROWS, _accuracy)
)
NB_TABLE_HTML = (
    '<table border="1" class="dataframe">'
    f"<thead><tr>{_header}</tr></thead><tbody>{_body}</tbody></table>"
)

NOTEBOOK_DOCS["nb-demo"] = {
    "version": 1,
    "language": "python",
    "cells": [
        {
            "id": "nb-md-1",
            "type": "markdown",
            "source": """# 学习记录分析

> 数据范围：2026-10-06 至 2026-10-18 ｜ 分析人：许澄
>
> 这个 Notebook 演示三件事：用 pandas 汇总学习记录、把 DataFrame 直接渲染成表格、把结论写回同一篇文档。代码单元格可以直接运行。

下面的数据来自本库「学习」页的知识点掌握度与练习记录（已做脱敏与取整）。""",
            "outputs": [],
            "execution_count": None,
        },
        {
            "id": "nb-code-1",
            "type": "code",
            "source": """import pandas as pd

records = [
    ("笔记工作区", 0.86, 12, 11),
    ("双向链接", 0.80, 10, 9),
    ("知识库", 0.78, 9, 8),
    ("Wiki 编译", 0.72, 11, 9),
    ("学习图谱", 0.68, 8, 6),
    ("学习闭环", 0.65, 6, 5),
    ("画布", 0.62, 7, 5),
    ("Notebook", 0.58, 6, 4),
    ("学习模式", 0.57, 9, 6),
    ("数据表视图", 0.54, 7, 4),
    ("间隔重复", 0.40, 8, 4),
    ("导入流水线", 0.34, 6, 3),
    ("仿真考试", 0.31, 5, 2),
]

df = pd.DataFrame(records, columns=["知识点", "掌握度", "练习题", "答对"])
df["正确率"] = (df["答对"] / df["练习题"] * 100).round(0).astype(int)

print(f"平均掌握度：{df['掌握度'].mean():.0%}")
print(f"总正确率：{df['答对'].sum() / df['练习题'].sum():.0%}")
print("最薄弱的三个知识点：", "、".join(df.nsmallest(3, "掌握度")["知识点"]))
""",
            "outputs": [
                {
                    "type": "stream",
                    "name": "stdout",
                    "text": NB_STREAM,
                }
            ],
            "execution_count": 1,
        },
        {
            "id": "nb-code-2",
            "type": "code",
            "source": """df.sort_values("掌握度")[["知识点", "掌握度", "正确率"]]""",
            "outputs": [
                {
                    "type": "execute_result",
                    "text": "按掌握度升序排列的知识点",
                    "html": NB_TABLE_HTML,
                }
            ],
            "execution_count": 2,
        },
        {
            "id": "nb-md-2",
            "type": "markdown",
            "source": """## 三点发现

1. **输入链路最弱**：导入流水线掌握度 34%，说明「资料进来之后发生了什么」还没有建立稳定心智；
2. **复习没有形成节奏**：间隔重复 40%，练习量不少（8 题）但正确率只有 50%，属于「做过但没记住」；
3. **考试暴露了边界问题**：仿真考试 31%，其中判断题失分最多，定义边界需要再读原文。

## 下一步

- 本周优先清空到期复习，再做一轮定向训练；
- 回到 [[复习与仿真考试]] 重读「复习队列」与「成绩怎么看」；
- 每完成一次仿真考试，就把薄弱知识点加进下一次学习计划。

> 结论不是终点：把这段文字留在 Notebook 里，下次复盘可以直接对照数据变化。""",
            "outputs": [],
            "execution_count": None,
        },
    ],
}

# 注入画布 / Notebook / 数据表 props
for _key, _doc in CANVAS_DOCS.items():
    NOTES_BY_KEY[_key]["props"]["canvas_doc"] = _doc
for _key, _doc in NOTEBOOK_DOCS.items():
    NOTES_BY_KEY[_key]["props"]["notebook_doc"] = _doc
for _key, _db in DATABASES.items():
    NOTES_BY_KEY[_key]["props"]["collection"] = {
        "name": _db["name"],
        "description": _db["description"],
        "fields": _db["fields"],
        "views": _db["views"],
    }

# --------------------------------------------------------------------------- #
# Wiki 页面
# --------------------------------------------------------------------------- #

WIKI_PAGES: list[dict] = [
    {
        "slug": "kiwi",
        "title": "Kiwi",
        "page_type": "entity",
        "body": """
# Kiwi

> Kiwi 是一个本地优先的个人知识工作台：把笔记、资料、画布、数据表与 Wiki 放在同一个知识库中，再用图谱与学习模式把内容变成可理解、可记忆的知识。

## 它解决什么问题

- **资料散落**：导入、外链与笔记统一进入知识库，按目录与标签组织；
- **关系看不见**：双向链接、反向链接与知识图谱把引用显性化；
- **学完就忘**：知识点、间隔重复与仿真考试形成学习闭环。

## 组成部分

- [[笔记工作区]]：文档、画布、数据表、Notebook、导入与外链；
- [[Wiki 编译]]：把资料整理成可引用的页面；
- [[知识图谱]]：可视化页面、笔记与它们的关系；
- [[学习模式]]：从 Wiki 生成练习并安排复习。

## 边界

Kiwi 不替代团队协作文档，也不提供实时多人编辑。它更适合个人或小团队沉淀主题知识：内容归自己所有，数据保存在本地数据库中，模型与向量服务可以按知识库配置。

## 来源

- 本库「欢迎使用 Kiwi」与「界面地图」笔记
- Kiwi 功能速查表 · 第 1 节「输入」
""",
    },
    {
        "slug": "knowledge-base",
        "title": "知识库",
        "page_type": "concept",
        "body": """
# 知识库

> 知识库是 Kiwi 中所有数据的隔离锚点：笔记、Wiki、素材、向量索引、学习画像都归属于某一个知识库。

## 定义与边界

- 每个知识库有独立的目录树、标签、模板与学习画像；
- 切换知识库时，搜索、图谱与学习数据都不会串库；
- 一个知识库可以单独配置 Embedding 模型与大模型；
- 内置演示库是一个特殊知识库：支持隐藏与还原，不提供彻底删除入口。

## 内置库与还原

内置库的「删除」是软删除：数据、素材与向量都会保留，只是从知识库列表隐藏。在知识库页面打开「内置知识库」卡片，点击「还原」即可恢复。普通知识库删除后才会清理库内数据与向量。

## 建议的拆分方式

| 场景 | 建议 |
|---|---|
| 个人学习 | 一个主题一个库 |
| 团队项目 | 一个项目一个库 |
| 长期资料 | 按领域拆分，避免单库过大 |

## 相关页面

[[标签与模板]] · [[导入流水线]] · [[Kiwi]]
""",
    },
    {
        "slug": "notes-workspace",
        "title": "笔记工作区",
        "page_type": "concept",
        "body": """
# 笔记工作区

> 笔记工作区由左侧目录树与右侧编辑区组成，支持文档、画布、数据表、Notebook、导入与外链六种条目。

## 六种条目

| 类型 | 用途 | 编辑体验 |
|---|---|---|
| 文档 | 长文、会议纪要、学习笔记 | Markdown + 块命令 |
| 画布 | 架构图、流程图、思维导图 | 无限画布、智能连线 |
| 数据表 | 任务、台账、术语表 | 表格 / 看板 / 画册 / 日历 |
| Notebook | 数据分析与演示 | 代码单元 + 输出 |
| 导入 | 从文件生成的笔记 | 可编辑，保留来源 |
| 外链 | 从网页抓取的正文 | 可编辑，保留原链接 |

## 目录与标签

目录树支持拖拽排序、移动分组与递归删除；标签是跨目录维度。条目可以固定、归档或移入回收站。

## 自动保存

正文、标题与视图模式在停止输入约 800ms 后自动保存；切换条目前会强制保存一次，避免内容丢失。

## 相关页面

[[双向链接]] · [[画布]] · [[数据表视图]] · [[Notebook]] · [[外链笔记]]
""",
    },
    {
        "slug": "canvas",
        "title": "画布",
        "page_type": "concept",
        "body": """
# 画布

> 画布是一块无限延展的绘图空间，用来表达难以用段落描述的结构、流程与关系。

## 能力

- **形状库**：矩形、圆角、椭圆、菱形、便签、文本、UML 类图、表格、网络设备；
- **智能连接**：从节点边缘拖出连线，靠近目标节点时自动吸附到最近锚点，移动节点后连线保持连接；
- **对齐辅助**：拖动时显示对齐线，支持等距与中心对齐；
- **主题**：工程、蓝图、纸张、深夜四种主题；
- **模板**：流程图、系统架构、时序图、思维导图；
- **网格与吸附**：可关闭，便于自由排版。

## 适用场景

- 系统架构与部署边界；
- 业务流程、状态机、接口时序；
- 讨论提纲与主题拆解；
- 学习笔记中的概念关系。

## 相关页面

[[笔记工作区]] · [[知识图谱]]
""",
    },
    {
        "slug": "database-views",
        "title": "数据表视图",
        "page_type": "concept",
        "body": """
# 数据表视图

> 数据表把一组结构化记录放在同一份数据上，用不同视图呈现，而不是复制成多张表。

## 字段类型

文本、长文本、数字、单选、多选、日期、复选框、网址、评分。字段类型会在写入时校验，避免脏数据。

## 四种视图

| 视图 | 适合 | 关键配置 |
|---|---|---|
| 表格 | 批量录入与对比 | 隐藏字段、排序、筛选 |
| 看板 | 按状态推进任务 | 分组字段 |
| 画册 | 卡片式浏览 | 封面字段、标题字段 |
| 日历 | 按日期安排 | 日期字段、标题字段 |

## 使用建议

1. 主字段选择可读性最好的文本字段；
2. 状态用单选而不是自由文本，才能稳定分组；
3. 日期统一使用 `YYYY-MM-DD`，避免时区偏移；
4. 同一批行只维护一份，视图只改变呈现方式。

## 相关页面

[[笔记工作区]] · [[标签与模板]]
""",
    },
    {
        "slug": "notebook",
        "title": "Notebook",
        "page_type": "concept",
        "body": """
# Notebook

> Notebook 把「分析过程」和「分析结论」放在同一篇笔记里：代码单元可执行，输出与文字一起保存。

## 单元格

- **Markdown 单元**：写背景、假设与结论；
- **代码单元**：Python，可以使用项目依赖中的 pandas、numpy、matplotlib 等；
- **输出**：标准输出、富文本表格、图片与错误信息都会保留在文档里。

## 适用场景

- 学习记录统计与趋势分析；
- 导入数据的质量检查；
- 知识库指标复盘；
- 需要重复运行的轻量计算。

## 注意

Notebook 的执行环境是本地沙箱，重启后内核会重新初始化。重要结论应写在 Markdown 单元中，避免只存在于输出里。

## 相关页面

[[笔记工作区]] · [[导入流水线]]
""",
    },
    {
        "slug": "import-pipeline",
        "title": "导入流水线",
        "page_type": "concept",
        "body": """
# 导入流水线

> 导入不是简单地上传文件，而是一条「解析 → 切块 → 向量化 → 可供编译 / 检索」的流水线。

## 处理步骤

1. **安全扫描**：文件类型白名单、大小限制与启发式检查；
2. **解析**：Markdown、PDF、DOCX、TXT、HTML 提取正文，记录解析质量；
3. **去重**：按 sha256 判断重复文件，重复时复用已有素材；
4. **切块与向量化**：按语义切分并写入向量索引；
5. **生成笔记**：把正文写入可编辑的导入笔记，保留来源；
6. **编译 Wiki**：需要时再执行，生成可引用的页面。

## 解析质量

解析结果会标记为 `clean`、`partial` 等状态，并附带警告。扫描版 PDF 可能只得到少量文字，建议先 OCR 或换用原始文档。

## 相关页面

[[Wiki 编译]] · [[Notebook]] · [[Kiwi 功能速查表]]
""",
    },
    {
        "slug": "link-notes",
        "title": "外链笔记",
        "page_type": "concept",
        "body": """
# 外链笔记

> 外链笔记把网页正文抓取到本地，变成可编辑、可检索、可引用的知识资产。

## 抓取行为

- 只接受 `http(s)` 链接，拒绝带凭据与私网 / 回环地址；
- 每次重定向都会重新校验目标地址；
- 有超时与大小上限；
- 成功时保存标题、站点、摘要、favicon 与最终 URL；
- 失败时仍创建书签卡片，之后可以手动补充或重新抓取。

## 为什么要本地化

网页会失效、改版或被删除。抓取后的正文进入知识库，可以参与搜索、Wiki 编译与学习；原始 URL 仅作为溯源信息保留。

## 相关页面

[[双向链接]] · [[笔记工作区]]
""",
    },
    {
        "slug": "wiki-compile",
        "title": "Wiki 编译",
        "page_type": "concept",
        "body": """
# Wiki 编译

> 编译把零散资料整理成标题稳定、带来源、互相引用的页面网络。

## 输入与输出

- 输入：导入的素材（Markdown / PDF / DOCX / HTML 等）；
- 输出：实体、概念、摘要、综合四类页面；
- 每页保存 `compiled_from_source_ids`，可追溯来源；
- 正文中的 `[[页面]]` 会转成 Wiki 链接。

## 增量与保护

重复编译时，系统只更新受影响的页面。人工编辑过的页面进入保护状态，不会被自动覆盖；若素材变化，会显示「源素材已更新」提示。

## 质量检查

编译后可以运行 Lint：检查缺失来源、悬空链接、孤立页面与前后矛盾。Lint 报告不修改正文，只给出待处理清单。

## 相关页面

[[知识图谱]] · [[导入流水线]] · [[双向链接]] · [[Kiwi 功能速查表]]
""",
    },
    {
        "slug": "bidirectional-links",
        "title": "双向链接",
        "page_type": "concept",
        "body": """
# 双向链接

> 双向链接让引用变成双向可导航的关系：A 引用 B，B 能看到「被 A 引用」。

## 两种写法

- `[[标题]]`：按标题匹配笔记或 Wiki 页面；
- `@` 提及：按 ID 引用，目标改名后仍然有效。

## 解析时机

笔记保存时重建链接：先删除旧的出链，再按正文重新写入。反向链接不需要手动维护，它来自其他笔记的出链。

## 在图谱中的表现

- 笔记之间的链接显示为「笔记双向链接」；
- 笔记与 Wiki 页面的关联显示为「笔记关联 Wiki」；
- Wiki 页面之间的 `[[...]]` 显示为「引用」。

## 使用建议

- 重要概念使用 @ 提及，避免改名断链；
- 每篇笔记至少有一条出链或入链，减少孤立节点；
- 定期用图谱的完整模式检查孤立页面。

## 相关页面

[[知识图谱]] · [[笔记工作区]]
""",
    },
    {
        "slug": "knowledge-graph",
        "title": "知识图谱",
        "page_type": "concept",
        "body": """
# 知识图谱

> 知识图谱把笔记、Wiki 页面与关系画成一张可交互的星图。

## 读图

- 节点颜色区分实体、概念、摘要、综合、笔记与 Wiki；
- 连线表示引用、相关、笔记双向链接、笔记关联 Wiki 与矛盾标记；
- 学习模式下，节点亮度表示掌握度：暗星优先学习；
- 悬停节点高亮一度邻居，移出后恢复。

## 两种密度

| 模式 | 特点 | 适用 |
|---|---|---|
| 精要 | 隐藏「相关」边、合并重复边、限制每节点关系数 | 日常浏览 |
| 完整 | 展示全部关系 | 结构检查 |

## 筛选与聚焦

可以勾选「包含笔记节点」，或只查看当前选中节点的邻域。刷新布局会重新计算力导向布局，但不改变缩放比例。

## 相关页面

[[Wiki 编译]] · [[学习模式]] · [[双向链接]]
""",
    },
    {
        "slug": "study-mode",
        "title": "学习模式",
        "page_type": "concept",
        "body": """
# 学习模式

> 学习模式把 Wiki 页面变成可出题、可评分、可复习的知识点。

## 进入前

需要先建立学习画像：目标类型、基础水平、每日时长、重点与薄弱领域。画像决定题目难度、知识覆盖与计划节奏。

## 三种练习

- **渐进训练**：一题一练，即时反馈；
- **复习队列**：按到期时间巩固；
- **仿真考试**：整卷计时、统一评分。

## 掌握度

掌握度是 0–1 的连续值，事实源保存在画像中。答对提高、答错降低；知识点页同时记录前置关系与内容指纹，Wiki 更新后可以提示重新学习。

## 边界

学习批注属于个人学习数据，只出现在学习模式，不写回 Wiki 正文。

## 相关页面

[[学习画像]] · [[间隔重复]] · [[仿真考试]] · [[知识图谱]]
""",
    },
    {
        "slug": "spaced-repetition",
        "title": "间隔重复",
        "page_type": "concept",
        "body": """
# 间隔重复

> 间隔重复根据记忆难度安排下一次复习时间，把有限时间用在最容易遗忘的内容上。

## 状态

每个知识点维护：

- 难度系数（ease factor）；
- 当前间隔天数；
- 连续正确次数；
- 到期时间与上次结果。

## 规则

- 首次学习后间隔较短；
- 连续答对时间隔增长；
- 答错后缩短间隔并重新计入近期队列；
- 到期知识点进入复习队列，逾期会标记。

## 实践建议

- 每天先清到期队列，再做新练习；
- 不要一次堆积几十条到期项，宁可每天少量；
- 仿真考试暴露的薄弱点，应加入下一次复习。

## 相关页面

[[学习模式]] · [[仿真考试]]
""",
    },
    {
        "slug": "mock-exam",
        "title": "仿真考试",
        "page_type": "concept",
        "body": """
# 仿真考试

> 仿真考试用整卷计时检验阶段性掌握度，并生成可行动的成绩单。

## 流程

1. 选择试卷模板与时长；
2. 按知识覆盖与难度分布组卷；
3. 作答期间切出学习模式会自动暂停计时；
4. 交卷后自动评分：客观题按答案，主观题按评分维度；
5. 输出总分、分项得分、薄弱知识点与时间分析。

## 成绩单

- 总分与合格线；
- 各题型得分率；
- 薄弱知识点及其掌握度；
- 各题型用时与异常（例如某题停留过久）。

## 相关页面

[[学习画像]] · [[间隔重复]]
""",
    },
    {
        "slug": "study-profile",
        "title": "学习画像",
        "page_type": "concept",
        "body": """
# 学习画像

> 学习画像是学习模式的输入：目标、基础、时间与掌握度共同决定每天该学什么。

## 包含什么

- 目标类型：领域学习、考试备考、项目速成；
- 基础水平：零基础、有基础、进阶；
- 每日可用时长；
- 重点领域与薄弱领域；
- 知识点掌握度映射；
- 学习计划与考试历史。

## 如何更新

完成练习、复习或考试后，系统自动更新掌握度与薄弱标记；用户也可以手动调整每日时长、重点领域与目标日期。

## 相关页面

[[学习模式]] · [[仿真考试]]
""",
    },
    {
        "slug": "tags-templates",
        "title": "标签与模板",
        "page_type": "concept",
        "body": """
# 标签与模板

> 目录解决位置，标签解决维度，模板解决「每次从哪里开始」。

## 标签

- 知识库级维度，可跨目录聚合；
- 一篇笔记可有多个标签；
- 建议保持扁平、少量、可合并。

## 模板

模板保存标题格式、正文骨架、默认标签与属性。创建笔记时选择模板即可预填；`{占位符}` 会在创建时替换。

## 维护建议

- 每月检查一次标签，合并同义项；
- 模板只保留高频结构，避免过度设计；
- 模板更新不会重写旧笔记。

## 相关页面

[[知识库]] · [[笔记工作区]]
""",
    },
    {
        "slug": "feature-cheatsheet",
        "title": "Kiwi 功能速查表",
        "page_type": "summary",
        "body": """
# Kiwi 功能速查表

> 对导入资料《Kiwi 功能速查表》的摘要：按输入、整理、理解、掌握四段组织全部核心能力。

## 输入

- 新建文档、导入文件、外链抓取、快速记录；
- 支持 Markdown、PDF、DOCX、TXT、HTML；
- 重复文件按 sha256 去重。

> 来源：Kiwi 功能速查表 · 1. 输入

## 整理

- 目录树、标签、模板；
- 数据表四种视图；
- 画布支持工程图与思维导图。

> 来源：Kiwi 功能速查表 · 2. 整理

## 理解

- Wiki 编译与来源溯源；
- `[[...]]` / @ 双向链接；
- 知识图谱精要 / 完整 / 掌握度模式；
- 基于知识库的问答与引用。

> 来源：Kiwi 功能速查表 · 3. 理解

## 掌握

- 学习画像、渐进训练、复习队列、仿真考试、学习批注；
- 推荐节奏：每天清队列，每周编译，每两周考试。

> 来源：Kiwi 功能速查表 · 4. 掌握

## 相关页面

[[Wiki 编译]] · [[学习模式]] · [[笔记工作区]]
""",
    },
    {
        "slug": "team-kb-in-three-weeks",
        "title": "三周搭建团队知识库",
        "page_type": "synthesis",
        "body": """
# 三周搭建团队知识库

> 综合示例项目简报与功能速查表，总结一个五人团队从零搭建知识库的路径。

## 三周结构

| 周次 | 主题 | 关键动作 | 产出 |
|---|---|---|---|
| 第 1 周 | 收集与归类 | 导入、去重、目录、标签 | 素材清单与目录树 |
| 第 2 周 | 编译与连接 | Wiki 编译、补链、清理孤立页 | 页面网络 |
| 第 3 周 | 学习与验收 | 画像、练习、考试、复盘 | 学习报告 |

> 来源：三周搭建团队知识库 · 项目节奏

## 验收标准

- 核心概念覆盖率 ≥ 90%；
- 孤立页面占比 < 5%；
- 新人仿真考试总分 ≥ 80；
- 每位成员能独立完成导入 → 编译 → 学习闭环。

## 关键经验

1. 先把「素材来源」打通，再谈页面质量；
2. 图谱先看孤立点，再看暗星；
3. 考试不是目的，成绩单上的薄弱点才是下一步输入。

## 相关页面

[[知识库]] · [[导入流水线]] · [[Wiki 编译]] · [[Kiwi 功能速查表]]
""",
    },
    {
        "slug": "learning-loop",
        "title": "如何完成一次主题学习",
        "page_type": "synthesis",
        "body": """
# 如何完成一次主题学习

> 把 Kiwi 的各项能力串成一个可重复执行的学习闭环。

## 七步闭环

1. **选主题**：建一个知识库或一个一级目录；
2. **收资料**：导入文件、抓取网页、写快速笔记；
3. **整理**：目录 + 标签 + 模板，去掉重复与过期内容；
4. **编译**：生成 Wiki 页面，补齐来源与引用；
5. **看关系**：用图谱检查孤立页面与暗星；
6. **学与练**：画像 → 渐进训练 → 复习队列；
7. **检验**：仿真考试 → 成绩单 → 更新计划。

## 每一步的产物

| 步骤 | 产物 | 存放在哪 |
|---|---|---|
| 收集 | 素材、笔记 | 笔记工作区 |
| 整理 | 目录、标签、数据表 | 笔记工作区 |
| 编译 | Wiki 页面与链接 | Wiki |
| 看关系 | 图谱洞察 | 知识图谱 |
| 学习 | 掌握度、复习状态 | 学习模式 |
| 检验 | 成绩单与薄弱点 | 仿真考试 |

## 最小可行节奏

- 每天 20 分钟：清复习队列 + 5 题训练；
- 每周 1 小时：导入资料 + 编译 + 补链；
- 每两周 45 分钟：一次仿真考试 + 复盘。

## 相关页面

[[知识库]] · [[Wiki 编译]] · [[知识图谱]] · [[学习模式]] · [[间隔重复]] · [[仿真考试]]
""",
    },
]

WIKI_LINKS: list[tuple[str, str]] = [
    ("kiwi", "notes-workspace"),
    ("kiwi", "wiki-compile"),
    ("kiwi", "knowledge-graph"),
    ("kiwi", "study-mode"),
    ("knowledge-base", "tags-templates"),
    ("knowledge-base", "import-pipeline"),
    ("knowledge-base", "kiwi"),
    ("notes-workspace", "bidirectional-links"),
    ("notes-workspace", "canvas"),
    ("notes-workspace", "database-views"),
    ("notes-workspace", "notebook"),
    ("notes-workspace", "link-notes"),
    ("canvas", "notes-workspace"),
    ("canvas", "knowledge-graph"),
    ("database-views", "notes-workspace"),
    ("database-views", "tags-templates"),
    ("notebook", "notes-workspace"),
    ("notebook", "import-pipeline"),
    ("import-pipeline", "wiki-compile"),
    ("import-pipeline", "notebook"),
    ("import-pipeline", "feature-cheatsheet"),
    ("link-notes", "bidirectional-links"),
    ("link-notes", "notes-workspace"),
    ("wiki-compile", "knowledge-graph"),
    ("wiki-compile", "import-pipeline"),
    ("wiki-compile", "bidirectional-links"),
    ("wiki-compile", "feature-cheatsheet"),
    ("bidirectional-links", "knowledge-graph"),
    ("bidirectional-links", "notes-workspace"),
    ("knowledge-graph", "wiki-compile"),
    ("knowledge-graph", "study-mode"),
    ("knowledge-graph", "bidirectional-links"),
    ("study-mode", "study-profile"),
    ("study-mode", "spaced-repetition"),
    ("study-mode", "mock-exam"),
    ("study-mode", "knowledge-graph"),
    ("spaced-repetition", "study-mode"),
    ("spaced-repetition", "mock-exam"),
    ("mock-exam", "study-profile"),
    ("mock-exam", "spaced-repetition"),
    ("study-profile", "study-mode"),
    ("study-profile", "spaced-repetition"),
    ("tags-templates", "knowledge-base"),
    ("tags-templates", "notes-workspace"),
    ("feature-cheatsheet", "wiki-compile"),
    ("feature-cheatsheet", "study-mode"),
    ("feature-cheatsheet", "notes-workspace"),
    ("team-kb-in-three-weeks", "knowledge-base"),
    ("team-kb-in-three-weeks", "import-pipeline"),
    ("team-kb-in-three-weeks", "wiki-compile"),
    ("team-kb-in-three-weeks", "feature-cheatsheet"),
    ("learning-loop", "knowledge-base"),
    ("learning-loop", "wiki-compile"),
    ("learning-loop", "knowledge-graph"),
    ("learning-loop", "study-mode"),
    ("learning-loop", "spaced-repetition"),
    ("learning-loop", "mock-exam"),
]

# 后端只按 slug 重建引用边；正文统一改成 [[slug]]，渲染时仍显示中文标题。
_WIKI_TITLE_TO_SLUG = {page["title"]: page["slug"] for page in WIKI_PAGES}
for _page in WIKI_PAGES:
    _page["body"] = re.sub(
        r"\[\[([^\[\]]+?)\]\]",
        lambda m: f"[[{_WIKI_TITLE_TO_SLUG.get(m.group(1).strip(), m.group(1).strip())}]]",
        _page["body"],
    )

# --------------------------------------------------------------------------- #
# 素材（由笔记正文生成上传文件）
# --------------------------------------------------------------------------- #

SOURCE_DEFS = [
    {
        "key": "cheatsheet",
        "title": "Kiwi 功能速查表",
        "filename": "Kiwi 功能速查表.md",
        "note_key": "import-demo",
        "type": "md",
    },
    {
        "key": "project-brief",
        "title": "三周搭建团队知识库",
        "filename": "三周搭建团队知识库.md",
        "note_key": "project",
        "type": "md",
    },
]
SOURCE_ID = {item["key"]: uid(f"source:{item['key']}") for item in SOURCE_DEFS}

# --------------------------------------------------------------------------- #
# 学习数据
# --------------------------------------------------------------------------- #

TOPIC_DEFS = [
    ("knowledge-base", "知识库", 0.78, False, "知识库是 Kiwi 的数据隔离锚点，内置库支持隐藏与还原。"),
    ("notes-workspace", "笔记工作区", 0.86, False, "目录树与六种条目类型组成的工作区，支持自动保存与双向链接。"),
    ("canvas", "画布", 0.62, False, "无限画布、工程图形状、智能粘连、对齐辅助与四种主题。"),
    ("database-views", "数据表视图", 0.54, False, "同一批结构化记录在表格、看板、画册、日历四种视图间切换。"),
    ("notebook", "Notebook", 0.58, False, "代码单元、输出与 Markdown 结论保存在同一篇笔记中。"),
    ("import-pipeline", "导入流水线", 0.34, True, "文件经过安全扫描、解析、去重、切块与向量化后生成可编辑笔记。"),
    ("wiki-compile", "Wiki 编译", 0.72, False, "把素材整理成带来源、互相引用的实体、概念、摘要与综合页面。"),
    ("bidirectional-links", "双向链接", 0.80, False, "[[标题]] 与 @ 提及在保存时重建出链，反向链接由此自动生成。"),
    ("knowledge-graph", "知识图谱", 0.68, False, "以星图展示节点与关系，精要模式隐藏弱关系，亮度表示掌握度。"),
    ("study-mode", "学习模式", 0.57, False, "基于 Wiki 生成练习，支持渐进训练、复习队列与仿真考试。"),
    ("spaced-repetition", "间隔重复", 0.40, True, "按难度系数、间隔天数与连续正确次数安排下一次复习。"),
    ("mock-exam", "仿真考试", 0.31, True, "整卷计时、自动评分，输出分项得分与薄弱知识点。"),
    ("learning-loop", "学习闭环", 0.65, False, "选主题、收资料、编译、看关系、学与练、检验的七步循环。"),
]
TOPIC_BY_SLUG = {slug: (title, mastery, weak, summary) for slug, title, mastery, weak, summary in TOPIC_DEFS}

PROFILE_MASTERY = {slug: mastery for slug, _, mastery, _, _ in TOPIC_DEFS}

PROFILE = {
    "goal_type": "domain",
    "level_prior": "beginner",
    "daily_minutes": 30,
    "exam_template_id": None,
    "target_date": None,
    "preferred_mode": "auto",
    "topics_focus": ["notes-workspace", "wiki-compile", "knowledge-graph", "study-mode", "spaced-repetition"],
    "weak_areas": ["import-pipeline", "spaced-repetition", "mock-exam"],
    "mastery": PROFILE_MASTERY,
    "profile_json": {
        "role": "刚接触 Kiwi 的新用户",
        "context": "希望通过一个完整示例掌握笔记、Wiki、图谱与学习闭环",
        "preferred_explanation": "先给操作路径，再解释原理",
    },
    "onboarded": True,
    "status": "active",
}

QUESTION_DEFS = [
    {
        "key": "q-slash",
        "topic": "notes-workspace",
        "type": "single_choice",
        "difficulty": "basic",
        "question": "在 Kiwi 编辑器中，输入哪个字符可以打开块命令菜单？",
        "options": ["A. `/`", "B. `@`", "C. `[[`", "D. `#`"],
        "answer_index": 0,
        "explanation": "在空行输入 `/` 会打开块命令菜单，可插入标题、表格、代码块、图片等。",
    },
    {
        "key": "q-link-syntax",
        "topic": "bidirectional-links",
        "type": "single_choice",
        "difficulty": "basic",
        "question": "`[[页面标题]]` 在笔记中的主要作用是什么？",
        "options": [
            "A. 建立指向笔记或 Wiki 页面的双向链接",
            "B. 插入一张图片",
            "C. 新建一张数据表",
            "D. 启动复习队列",
        ],
        "answer_index": 0,
        "explanation": "`[[...]]` 按标题匹配笔记或 Wiki 页面，保存后目标页面会出现反向链接。",
    },
    {
        "key": "q-kanban",
        "topic": "database-views",
        "type": "single_choice",
        "difficulty": "basic",
        "question": "要把任务按「状态」分列并拖动卡片，应选择哪种数据表视图？",
        "options": ["A. 表格", "B. 看板", "C. 画册", "D. 日历"],
        "answer_index": 1,
        "explanation": "看板视图按单选字段分组，拖动卡片会直接修改该分组字段。",
    },
    {
        "key": "q-import-order",
        "topic": "import-pipeline",
        "type": "single_choice",
        "difficulty": "medium",
        "question": "导入一份文件后，系统默认经历哪条处理链路？",
        "options": [
            "A. 解析 → 切块 → 向量化 → 生成可编辑笔记",
            "B. 编译 → 排版 → 打印",
            "C. 抓取 → 摘要 → 分享",
            "D. 识别 → 翻译 → 导出",
        ],
        "answer_index": 0,
        "explanation": "导入先做安全扫描与解析，再切块、向量化，并把正文写入可编辑的导入笔记。",
    },
    {
        "key": "q-graph-brightness",
        "topic": "knowledge-graph",
        "type": "single_choice",
        "difficulty": "basic",
        "question": "学习模式下，图谱节点亮度主要表达什么？",
        "options": ["A. 创建时间", "B. 掌握度", "C. 文件大小", "D. 标签数量"],
        "answer_index": 1,
        "explanation": "亮度映射掌握度：暗星表示尚未掌握，应优先学习。",
    },
    {
        "key": "q-review-due",
        "topic": "spaced-repetition",
        "type": "single_choice",
        "difficulty": "medium",
        "question": "复习队列中下一道题什么时候出现，主要由什么决定？",
        "options": [
            "A. 笔记修改时间",
            "B. 间隔重复算法计算的到期时间",
            "C. 知识库创建顺序",
            "D. 手动拖动顺序",
        ],
        "answer_index": 1,
        "explanation": "每个知识点维护难度、间隔与连续正确次数，到期时间由间隔重复算法计算。",
    },
    {
        "key": "q-exam-pause",
        "topic": "mock-exam",
        "type": "single_choice",
        "difficulty": "basic",
        "question": "仿真考试进行中切换到其他模式，计时会怎样？",
        "options": ["A. 继续计时", "B. 自动暂停", "C. 直接交卷", "D. 重置为 0"],
        "answer_index": 1,
        "explanation": "切出学习模式即暂停计时，返回后继续，避免离开页面造成不公平失分。",
    },
    {
        "key": "q-canvas-snap",
        "topic": "canvas",
        "type": "single_choice",
        "difficulty": "basic",
        "question": "把连接线拖到另一个节点附近时，画布会怎样处理？",
        "options": [
            "A. 自动吸附到最近的锚点",
            "B. 删除连接线",
            "C. 转换为文本",
            "D. 强制水平",
        ],
        "answer_index": 0,
        "explanation": "连接线会智能吸附到目标节点最近的锚点，移动节点后连接关系保持。",
    },
    {
        "key": "q-builtin-delete",
        "topic": "knowledge-base",
        "type": "true_false",
        "difficulty": "basic",
        "question": "删除内置演示知识库会永久清除数据，无法还原。",
        "options": ["正确", "错误"],
        "answer_index": 1,
        "explanation": "内置库是软删除：数据、素材与向量保留，可在知识库页点击「还原」恢复。",
    },
    {
        "key": "q-mention-backlink",
        "topic": "bidirectional-links",
        "type": "true_false",
        "difficulty": "medium",
        "question": "笔记中的 @ 提及与 `[[...]]` 引用都会生成反向链接。",
        "options": ["正确", "错误"],
        "answer_index": 0,
        "explanation": "两种写法都会在保存时重建出链，目标页面据此显示反向链接。",
    },
    {
        "key": "q-loop-short",
        "topic": "wiki-compile",
        "type": "short_answer",
        "difficulty": "medium",
        "question": "简述从一份导入资料到可复习知识点的完整链路，并说明每一步产生的结果。",
        "min_words": 120,
        "requirements": "至少覆盖导入、编译、图谱、学习四个环节，并说明每步的产物。",
        "key_points": [
            "导入后生成可编辑笔记与素材来源",
            "编译生成 Wiki 页面与引用关系",
            "图谱展示页面、笔记与关系",
            "学习模式把 Wiki 页面转为知识点并出题",
            "复习队列按间隔重复安排巩固",
        ],
        "reference_answer": "资料导入后先经过解析、切块与向量化，生成可编辑的导入笔记并保留素材来源；执行 Wiki 编译后，系统抽取实体、概念与摘要，生成带来源和引用的页面；知识图谱把 Wiki 页面与笔记的关系可视化，便于检查孤立页面与薄弱区域；进入学习模式后，Wiki 页面成为可出题的知识点，系统按画像生成练习并记录掌握度；答错或不确定的内容进入复习队列，按间隔重复算法安排下一次复习。每一步都把上一部的产物作为输入，形成可追溯的闭环。",
        "explanation": "评分关注链路完整性与每步产物，缺少任一环节按比例扣分。",
    },
    {
        "key": "q-graph-compact",
        "topic": "knowledge-graph",
        "type": "short_answer",
        "difficulty": "medium",
        "question": "说明精要图谱与完整图谱的区别，并各举一个适用场景。",
        "min_words": 100,
        "requirements": "说明两种模式在边的取舍、节点密度与适用场景上的差异。",
        "key_points": [
            "精要模式隐藏相关边并合并重复边",
            "精要模式限制每节点关系数，保持稀疏",
            "完整模式展示全部关系",
            "精要适合日常浏览，完整适合结构检查",
        ],
        "reference_answer": "精要模式会隐藏自动生成的「相关」边、合并同一对节点的重复边，并限制每个节点保留的关系数量，因此图更稀疏、适合日常浏览与快速定位主题；完整模式保留全部关系，可以看到弱关联与孤立页面，适合结构检查、补链和排查命名冲突。两者使用同一批节点与关系数据，只是呈现密度不同。",
        "explanation": "评分关注两种模式的取舍与场景匹配。",
    },
    {
        "key": "q-review-factors",
        "topic": "spaced-repetition",
        "type": "short_answer",
        "difficulty": "medium",
        "question": "一道题再次出现在复习队列的时间会受哪些因素影响？请至少说明三个。",
        "min_words": 100,
        "requirements": "结合间隔重复的状态字段说明。",
        "key_points": [
            "上次作答是否正确",
            "难度系数",
            "当前间隔天数与连续正确次数",
            "到期时间与逾期情况",
        ],
        "reference_answer": "复习间隔受上次作答结果影响：答对会延长间隔，答错会缩短间隔并重新进入近期队列；难度系数越高，间隔增长越慢；连续正确次数越多，间隔越长；系统还会根据当前间隔天数计算下一次到期时间，逾期未复习的知识点会优先出现在队列中。",
        "explanation": "评分关注是否覆盖结果、难度、间隔与到期四个因素中的至少三个。",
    },
    {
        "key": "q-team-case",
        "topic": "knowledge-base",
        "type": "case_analysis",
        "difficulty": "hard",
        "question": "团队知识库上线两个月后，成员反馈「搜不到、找不到、学了记不住」，请诊断并给出改进方案。",
        "material": "某五人产品团队用 Kiwi 搭建知识库两个月，积累了 180 篇笔记和 40 个 Wiki 页面。近期反馈集中在三点：搜索关键词经常搜不到；新人不知道从哪篇开始读；成员完成了学习练习，但两周后同一知识点仍然答错。团队目前没有统一标签，Wiki 页面有 12 个孤立页面，复习队列长期积压。",
        "requirements": "请从内容结构、链接与图谱、学习闭环三个维度诊断，并给出可执行的改进措施。答案不少于 200 字。",
        "min_words": 200,
        "key_points": [
            "内容结构：统一标签与命名，建立目录与模板",
            "链接与图谱：补双向链接，清理孤立页面",
            "学习闭环：清空复习队列，按到期时间安排",
            "用仿真考试暴露薄弱点并回流到 Wiki",
        ],
        "rubric": [
            {"key": "diagnosis", "label": "问题诊断", "weight": 0.4, "description": "能分别指出结构、链接与学习闭环三个层面的问题。"},
            {"key": "solution", "label": "改进方案", "weight": 0.4, "description": "措施具体可执行，覆盖标签、补链、复习与考试。"},
            {"key": "priority", "label": "优先级与节奏", "weight": 0.2, "description": "给出合理的实施顺序与验证指标。"},
        ],
        "reference_answer": "问题不在内容数量，而在结构、连接与学习节奏。内容层面：缺少统一标签与命名规范，导致检索词与正文用词不一致；应建立 10–15 个受控标签、统一概念命名，并用模板固定高频文档结构。链接层面：12 个孤立页面说明引用网络断裂；应在图谱完整模式中逐个补链，把新页面接入至少一个已有主题，并每周检查孤立率。学习层面：复习队列积压说明到期内容没有被处理；应每天先清队列，再做新练习，并用仿真考试的成绩单定位薄弱知识点，回流到对应 Wiki 页面重读。建议先做两周的「清积压 + 补链」，再引入每周固定的编译与复盘节奏，用孤立页面占比、复习清零天数和考试总分作为验证指标。",
        "explanation": "评分维度：问题诊断 40%，方案可执行性 40%，优先级与验证指标 20%。",
    },
    {
        "key": "q-onboarding-case",
        "topic": "study-mode",
        "type": "case_analysis",
        "difficulty": "hard",
        "question": "新成员入职，要求两周内能独立使用 Kiwi 完成资料整理与学习，请设计一个导入方案。",
        "material": "新成员没有使用过知识库工具，每天可投入 40 分钟。团队已有 60 篇笔记、25 个 Wiki 页面和一套功能速查表，但还没有学习画像与练习记录。团队希望两周后新成员能独立完成「导入一份资料 → 编译 Wiki → 完成一次练习」的闭环。",
        "requirements": "请给出两周计划，说明学习画像、内容路径、练习与验收方式。答案不少于 200 字。",
        "min_words": 200,
        "key_points": [
            "建立画像：目标、基础、每日时长",
            "第一周：界面与笔记工作区，完成导入与编译",
            "第二周：图谱与学习闭环，完成练习与一次小测",
            "验收：独立完成闭环并达到目标分数",
        ],
        "rubric": [
            {"key": "profile", "label": "画像与目标", "weight": 0.25, "description": "设置了目标、基础与每日时长。"},
            {"key": "path", "label": "两周路径", "weight": 0.35, "description": "内容由浅入深，覆盖导入、编译、图谱与学习。"},
            {"key": "practice", "label": "练习与验收", "weight": 0.4, "description": "有可量化的验收标准与反馈机制。"},
        ],
        "reference_answer": "先建立学习画像：目标设为「项目速成」，基础为初学者，每日 40 分钟，重点放在笔记工作区、导入流水线与 Wiki 编译。第一周：前三天阅读欢迎页、一分钟上手与文档编辑，完成一次新建、表格与双向链接练习；后两天导入功能速查表，执行一次 Wiki 编译并查看来源；周末用图谱完整模式找出一个孤立页面并补链。第二周：前两天学习知识图谱与学习模式，完成 20 道渐进训练；中间两天清空复习队列并做一次 10 题小测；最后一天独立完成「导入 → 编译 → 练习」闭环，验收标准为流程无阻塞、小测正确率 ≥ 80%、能解释至少三个核心概念。每天用 5 分钟记录卡点，导师次日集中解答。",
        "explanation": "评分维度：画像 25%，路径 35%，练习与验收 40%。",
    },
]

# --------------------------------------------------------------------------- #
# 练习 / 复习 / 考试
# --------------------------------------------------------------------------- #

PROFILE_ID = uid("profile:default")
QUESTION_ID = {item["key"]: uid(f"question:{item['key']}") for item in QUESTION_DEFS}
QUESTION_BY_KEY = {item["key"]: item for item in QUESTION_DEFS}

SESSIONS = [
    {
        "key": "drill",
        "question_count": 6,
        "correct_count": 4,
        "mode": "drill",
        "topic_slug": None,
        "status": "completed",
        "created_at": ts(120),
        "finished_at": ts(140),
    },
    {
        "key": "review",
        "question_count": 4,
        "correct_count": 3,
        "mode": "review",
        "topic_slug": "spaced-repetition",
        "status": "completed",
        "created_at": ts(160),
        "finished_at": ts(172),
    },
]
SESSION_ID = {item["key"]: uid(f"session:{item['key']}") for item in SESSIONS}

ATTEMPTS = [
    ("drill", "q-slash", True, 0, "", 22000, 122),
    ("drill", "q-link-syntax", True, 0, "", 31000, 126),
    ("drill", "q-kanban", True, 1, "", 18000, 130),
    ("drill", "q-import-order", False, 1, "", 42000, 134),
    ("drill", "q-graph-brightness", False, 2, "", 26000, 137),
    ("drill", "q-review-due", True, 1, "", 24000, 140),
    ("review", "q-builtin-delete", True, 1, "", 15000, 162),
    ("review", "q-mention-backlink", True, 0, "", 21000, 165),
    ("review", "q-exam-pause", True, 1, "", 14000, 168),
    ("review", "q-canvas-snap", False, 3, "", 33000, 172),
]

# 复习状态：due_at 以演示库生成时间（2026-10-18 09:00 UTC）为基准
REVIEWS = [
    ("knowledge-base", 2.6, 6.0, 3, "2026-10-20T08:00:00+00:00", "2026-10-14T08:00:00+00:00", True),
    ("notes-workspace", 2.7, 12.0, 4, "2026-10-26T08:00:00+00:00", "2026-10-14T08:00:00+00:00", True),
    ("canvas", 2.5, 3.0, 2, "2026-10-18T07:30:00+00:00", "2026-10-15T08:00:00+00:00", True),
    ("database-views", 2.45, 6.0, 3, "2026-10-22T08:00:00+00:00", "2026-10-16T08:00:00+00:00", True),
    ("notebook", 2.35, 3.0, 2, "2026-10-19T08:00:00+00:00", "2026-10-16T08:00:00+00:00", True),
    ("import-pipeline", 2.2, 2.0, 1, "2026-10-17T08:00:00+00:00", "2026-10-15T08:00:00+00:00", False),
    ("knowledge-graph", 2.55, 6.0, 3, "2026-10-24T08:00:00+00:00", "2026-10-18T08:00:00+00:00", True),
    ("spaced-repetition", 2.3, 2.0, 1, "2026-10-18T08:00:00+00:00", "2026-10-16T08:00:00+00:00", False),
    ("mock-exam", 2.4, 3.0, 2, "2026-10-21T08:00:00+00:00", "2026-10-18T08:00:00+00:00", True),
    ("wiki-compile", 2.5, 6.0, 3, "2026-10-23T08:00:00+00:00", "2026-10-17T08:00:00+00:00", True),
]

ANNOTATIONS = [
    {
        "target": "knowledge-graph",
        "content_md": "读图顺序：先看完整模式的孤立点，再切回精要模式看暗星。孤立点说明结构缺失，暗星说明还没有掌握，两者不要混在一起处理。",
        "quote": "每周看一次暗星与孤立点，就能找到知识库的结构性缺口。",
    },
    {
        "target": "spaced-repetition",
        "content_md": "到期队列不要一次清完：积压很多时分成两三天处理，否则当天的正确率会被疲劳拉低，反而缩短间隔。",
        "quote": "不要一次堆积几十条到期项，宁可每天少量。",
    },
]


def _question_json(item: dict) -> dict:
    is_choice = item["type"] in ("single_choice", "true_false")
    return {
        "options": item.get("options", []),
        "question": item["question"],
        "cite_slug": item["topic"],
        "difficulty": item["difficulty"],
        "explanation": item["explanation"],
        "answer_index": item.get("answer_index", -1) if is_choice else -1,
    }


def _answer_json(item: dict) -> dict:
    if item["type"] in ("single_choice", "true_false"):
        return {"correct_index": item["answer_index"]}
    payload = {
        "key_points": item.get("key_points", []),
        "reference_answer": item.get("reference_answer", ""),
    }
    if item.get("rubric"):
        payload["rubric"] = item["rubric"]
    return payload


def _body_json(item: dict) -> dict:
    if item["type"] in ("single_choice", "true_false"):
        return {}
    return {
        "material": item.get("material", ""),
        "scenario": "",
        "min_words": item.get("min_words", 100),
        "requirements": item.get("requirements", ""),
    }


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


QUESTIONS = [
    {
        "kb_id": str(KB_ID),
        "id": QUESTION_ID[item["key"]],
        "wiki_page_id": uid(f"wiki:{item['topic']}"),
        "topic_slug": item["topic"],
        "fingerprint": f"demo:{item['key']}",
        "question_type": item["type"],
        "question_json": _question_json(item),
        "body_json": _body_json(item),
        "answer_json": _answer_json(item),
        "difficulty": item["difficulty"],
        "source_hash": _source_hash(item["question"]),
        "web_sources_json": [],
        "confidence_level": "unverified",
        "cache_status": "active",
        "created_at": ts(150),
        "updated_at": ts(150),
    }
    for item in QUESTION_DEFS
]

EXAM_RESPONSES: dict[str, dict] = {
    "q-slash": {"selected": 0, "correct": True, "score": 5.0, "time": 32},
    "q-link-syntax": {"selected": 0, "correct": True, "score": 5.0, "time": 28},
    "q-kanban": {"selected": 1, "correct": True, "score": 5.0, "time": 24},
    "q-import-order": {"selected": 2, "correct": False, "score": 0.0, "time": 58},
    "q-graph-brightness": {"selected": 1, "correct": True, "score": 5.0, "time": 26},
    "q-review-due": {"selected": 1, "correct": True, "score": 5.0, "time": 31},
    "q-exam-pause": {"selected": 1, "correct": True, "score": 5.0, "time": 19},
    "q-canvas-snap": {"selected": 0, "correct": True, "score": 5.0, "time": 22},
    "q-builtin-delete": {"selected": 1, "correct": True, "score": 5.0, "time": 17},
    "q-mention-backlink": {"selected": 1, "correct": False, "score": 0.0, "time": 41},
    "q-loop-short": {
        "score": 8.5,
        "ratio": 0.85,
        "time": 245,
        "user_answer": "资料先导入，解析后变成可编辑笔记；编译 Wiki 会生成带来源的页面；图谱展示页面和笔记的关系；进入学习模式后，Wiki 页面变成知识点并生成练习；答错的题进入复习队列，按间隔重复再次出现。",
        "comment": "链路完整，但漏掉了切块与向量化的作用，且没有说明复习状态如何更新。",
    },
    "q-graph-compact": {
        "score": 8.0,
        "ratio": 0.8,
        "time": 210,
        "user_answer": "精要模式会隐藏相关边、合并重复边，节点更少，适合平时浏览；完整模式显示所有关系，适合检查孤立页面和补链接。",
        "comment": "两种模式的取舍说明清楚，可以再补充每节点关系数限制。",
    },
    "q-review-factors": {
        "score": 7.5,
        "ratio": 0.75,
        "time": 198,
        "user_answer": "答对会延长间隔，答错会缩短；难度系数会影响增长速度；连续答对次数越多间隔越长。到期后就会出现在队列里。",
        "comment": "覆盖了结果、难度与连续次数，遗漏了逾期优先与当前间隔天数。",
    },
    "q-team-case": {
        "score": 9.5,
        "ratio": 0.95,
        "time": 420,
        "user_answer": "问题分三层：第一，缺少统一标签和命名，导致搜不到；第二，12 个孤立页面说明链接网络断裂，新人不知道从哪读；第三，复习队列积压，学习没有形成节奏。改进上，先建立 10 到 15 个受控标签和命名规范，用模板固定高频文档；然后在图谱完整模式补齐链接，每周检查孤立率；最后每天先清到期复习，再用仿真考试定位薄弱点，把结果回流到 Wiki。验证指标用孤立页面占比、复习清零天数和考试总分。",
        "comment": "诊断与措施完整，优先级明确；可以再给出两周的清积压节奏。",
    },
    "q-onboarding-case": {
        "score": 9.0,
        "ratio": 0.9,
        "time": 405,
        "user_answer": "先设画像：目标项目速成、初学者、每天 40 分钟，重点放在笔记、导入和 Wiki。第一周前三天读入门内容并练习新建、表格、双向链接，后两天导入速查表、编译 Wiki、查看来源；周末用完整图谱找一个孤立页补链。第二周前两天学图谱和学习模式，做 20 道渐进训练；中间两天清复习队列并做 10 题小测；最后一天独立完成导入到练习的闭环。验收看流程是否无阻塞、小测正确率是否达到 80%、能否解释三个核心概念。",
        "comment": "计划完整、验收可量化；建议补充每日卡点记录与导师答疑机制。",
    },
}

EXAM_ID = uid("mock-exam:final")
EXAM_QUESTIONS = [item["key"] for item in QUESTION_DEFS]
EXAM_SECTION_NAMES = {
    "single_choice": "单项选择题",
    "true_false": "判断题",
    "short_answer": "简答题",
    "case_analysis": "案例分析",
}


def _section_of(question_type: str) -> str:
    return EXAM_SECTION_NAMES[question_type]


def _item_feedback(item: dict, response: dict) -> dict:
    is_choice = item["type"] in ("single_choice", "true_false")
    if is_choice:
        selected = int(response["selected"])
        correct_index = int(item["answer_index"])
        return {
            "ratio": 1.0 if response["correct"] else 0.0,
            "graded": True,
            "correct": bool(response["correct"]),
            "dimensions": [],
            "explanation": item["explanation"],
            "correct_index": correct_index,
            "correct_answer": item["options"][correct_index],
            "grading_method": "rule",
            "correct_indexes": [correct_index],
            "selected_indexes": [selected],
            "time_spent_seconds": response["time"],
        }
    rubric = item.get("rubric") or [
        {"key": "points", "label": "要点覆盖", "weight": 1.0, "description": "覆盖关键要点。"}
    ]
    ratio = float(response["ratio"])
    total = float(response["score"])
    dimensions = []
    for index, dim in enumerate(rubric):
        weight = float(dim.get("weight", 1.0))
        max_score = round(total / max(ratio, 0.01) * weight, 2)
        # 让各维度得分相加恰好等于总分
        score = round(total * weight, 2) if index < len(rubric) - 1 else round(
            total - sum(d["score"] for d in dimensions), 2
        )
        dimensions.append(
            {
                "key": dim["key"],
                "label": dim["label"],
                "score": score,
                "max_score": max_score,
                "comment": response.get("comment", ""),
            }
        )
    return {
        "ratio": ratio,
        "graded": True,
        "correct": ratio >= 0.6,
        "dimensions": dimensions,
        "explanation": item["explanation"],
        "correct_index": -1,
        "correct_answer": item.get("reference_answer", ""),
        "grading_method": "llm",
        "correct_indexes": [],
        "selected_indexes": [],
        "time_spent_seconds": response["time"],
    }


EXAM_SCORES = {
    "single_choice": (5.0, 40.0),
    "true_false": (5.0, 10.0),
    "short_answer": (10.0, 30.0),
    "case_analysis": (10.0, 20.0),
}

EXAM_ITEMS = []
for order, key in enumerate(EXAM_QUESTIONS):
    item = QUESTION_BY_KEY[key]
    response = EXAM_RESPONSES[key]
    EXAM_ITEMS.append(
        {
            "id": uid(f"exam-item:{key}"),
            "mock_exam_id": EXAM_ID,
            "question_id": QUESTION_ID[key],
            "order_index": order,
            "section_type": item["type"],
            "section_name": _section_of(item["type"]),
            "score": EXAM_SCORES[item["type"]][0],
            "user_answer": response.get("user_answer", ""),
            "selected_index": response.get("selected"),
            "score_awarded": response["score"],
            "feedback_json": _item_feedback(item, response),
            "answered_at": ts(210 + order),
            "created_at": ts(200),
            "updated_at": ts(210 + order),
        }
    )


def _exam_breakdown() -> dict:
    sections = []
    for section_type, (score, max_score) in EXAM_SCORES.items():
        items = [item for item in EXAM_ITEMS if item["section_type"] == section_type]
        awarded = sum(float(item["score_awarded"] or 0) for item in items)
        correct = sum(1 for item in items if item["feedback_json"].get("correct"))
        sections.append(
            {
                "name": EXAM_SECTION_NAMES[section_type],
                "type": section_type,
                "score": round(awarded, 2),
                "max_score": max_score,
                "accuracy": round(awarded / max_score, 3),
                "correct_count": correct,
                "question_count": len(items),
            }
        )

    by_topic: dict[str, dict] = {}
    for item, key in zip(EXAM_ITEMS, EXAM_QUESTIONS):
        question = QUESTION_BY_KEY[key]
        bucket = by_topic.setdefault(
            question["topic"],
            {
                "slug": question["topic"],
                "title": TOPIC_BY_SLUG[question["topic"]][0],
                "domain": "concept",
                "mastery": PROFILE_MASTERY[question["topic"]],
                "score": 0.0,
                "max_score": 0.0,
                "correct_count": 0,
                "question_count": 0,
            },
        )
        bucket["score"] = round(bucket["score"] + float(item["score_awarded"] or 0), 2)
        bucket["max_score"] = round(bucket["max_score"] + float(item["score"]), 2)
        bucket["question_count"] += 1
        if item["feedback_json"].get("correct"):
            bucket["correct_count"] += 1
    knowledge_points = list(by_topic.values())
    for point in knowledge_points:
        point["accuracy"] = round(point["score"] / max(point["max_score"], 0.01), 3)
    knowledge_points.sort(key=lambda point: point["accuracy"])
    weak_topics = [
        {
            "slug": point["slug"],
            "title": point["title"],
            "mastery": point["mastery"],
            "accuracy": point["accuracy"],
        }
        for point in knowledge_points
        if point["accuracy"] < 0.8
    ]
    total = round(sum(item["score_awarded"] or 0 for item in EXAM_ITEMS), 2)
    return {
        "max": 100.0,
        "total": total,
        "passed": total >= 60,
        "passing": 60.0,
        "accuracy": round(total / 100, 3),
        "sections": sections,
        "knowledge_points": knowledge_points,
        "weak_topics": weak_topics,
        "advice": "总分 82.5/100，已达到合格线。判断题正确率偏低，建议回到「间隔重复」与「双向链接」页面重读定义边界，并把薄弱知识点加入下一轮复习。",
        "time_analysis": {
            "used_minutes": 38,
            "duration_minutes": 45,
            "anomalies": [
                {"section": "单项选择题", "note": "第 4 题停留 58 秒，明显高于同题型均值。"}
            ],
            "per_section_seconds": {
                "单项选择题": 260,
                "判断题": 58,
                "简答题": 653,
                "案例分析": 825,
            },
        },
    }


EXAM_BREAKDOWN = _exam_breakdown()

MOCK_EXAMS = [
    {
        "kb_id": str(KB_ID),
        "id": EXAM_ID,
        "profile_id": PROFILE_ID,
        "exam_template_id": None,
        "title": "Kiwi 上手指南 · 结业测验",
        "status": "graded",
        "duration_minutes": 45,
        "question_count": len(EXAM_ITEMS),
        "total_score": EXAM_BREAKDOWN["total"],
        "max_score": 100.0,
        "passing_score": 60.0,
        "score_breakdown_json": EXAM_BREAKDOWN,
        "time_spent_json": {
            "used_seconds": 2280,
            "sections": EXAM_BREAKDOWN["time_analysis"]["per_section_seconds"],
        },
        "template_snapshot_json": {
            "name": "通用综合测验",
            "code": "generic_exam",
            "duration_minutes": 45,
        },
        "generation_progress": 1.0,
        "error": None,
        "started_at": "2026-10-18T10:00:00+00:00",
        "submitted_at": "2026-10-18T10:38:00+00:00",
        "paused_at": None,
        "paused_seconds": 75,
        "remaining_seconds": 420,
        "generated_at": ts(195),
        "created_at": ts(195),
        "updated_at": ts(238),
    }
]

STUDY_PLAN_DAYS = []
_focus_cycle = ["import-pipeline", "spaced-repetition", "mock-exam", "knowledge-graph", "database-views"]
for index in range(14):
    date = (datetime(2026, 10, 19, tzinfo=timezone.utc) + timedelta(days=index)).date().isoformat()
    mode = "mock" if index in (5, 12) else "drill"
    STUDY_PLAN_DAYS.append(
        {
            "date": date,
            "mode": mode,
            "focus": [_focus_cycle[index % len(_focus_cycle)], _focus_cycle[(index + 1) % len(_focus_cycle)]],
            "minutes": 30,
            "note": "整卷模拟与时间分配" if mode == "mock" else "薄弱点渐进训练",
            "adjusted": False,
        }
    )

STUDY_PLANS = [
    {
        "id": uid("plan:default"),
        "profile_id": PROFILE_ID,
        "kb_id": str(KB_ID),
        "phase": "initial",
        "suggested_mode": "drill",
        "plan_json": {
            "week": STUDY_PLAN_DAYS,
            "phase": "initial",
            "manual": {},
            "coverage": 0.54,
            "due_count": 3,
            "rationale": "当前覆盖知识面约 54%，先以薄弱点渐进训练建立基础；两周内安排两次整卷模拟。",
            "streak_days": 4,
            "weak_topics": ["import-pipeline", "spaced-repetition", "mock-exam"],
            "exam_history": {"count": 1, "passed": 1, "avg_rate": 0.825, "latest_rate": 0.825, "passing_known": 1},
            "accuracy_trend": 0.78,
            "days_to_target": None,
            "suggested_mode": "drill",
        },
        "computed_at": ts(240),
        "created_at": ts(240),
        "updated_at": ts(240),
    }
]

# --------------------------------------------------------------------------- #
# 组装 seed
# --------------------------------------------------------------------------- #

LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
# 编辑器 @ 提及的 Markdown 持久化格式：[@标题](kiwi://note/<uuid>)
NOTE_MENTION_RE = re.compile(
    r"\[@[^\]]*\]\(kiwi://note/([0-9a-f]{8}-[0-9a-f-]{27,})\)"
)
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def _prose(text: str) -> str:
    """去掉代码块与行内代码，避免把语法示例当成真实引用。"""
    return INLINE_CODE_RE.sub("", FENCE_RE.sub("", text))


def _line_context(body: str, start: int) -> str:
    line_start = body.rfind("\n", 0, start) + 1
    line_end = body.find("\n", start)
    if line_end == -1:
        line_end = len(body)
    return body[line_start:line_end].strip()[:180]


def _build_note_links() -> list[dict]:
    title_to_id = {note["title"]: note["id"] for note in NOTES}
    note_ids = {note["id"] for note in NOTES}
    links: dict[tuple[str, str], dict] = {}
    for note in NOTES:
        pairs: list[tuple[str, int]] = []
        for match in LINK_RE.finditer(note["body_md"]):
            target = title_to_id.get(match.group(1).strip())
            if target:
                pairs.append((target, match.start()))
        for match in NOTE_MENTION_RE.finditer(note["body_md"]):
            target = match.group(1)
            if target in note_ids:
                pairs.append((target, match.start()))
        for target, start in pairs:
            if target == note["id"]:
                continue
            pair = (note["id"], target)
            links.setdefault(
                pair,
                {
                    "from_note_id": note["id"],
                    "to_note_id": target,
                    "context_text": _line_context(note["body_md"], start),
                },
            )
    return list(links.values())


def _markdown(filename: str, content: str) -> str:
    """源文件标题；正文与笔记保持一致。"""
    return content if content.startswith("# ") else f"# {filename}\n\n{content}"


def _build_sources() -> tuple[list[dict], dict[str, str]]:
    rows: list[dict] = []
    contents: dict[str, str] = {}
    filenames = {
        "cheatsheet": "kiwi-feature-cheatsheet.md",
        "project-brief": "team-knowledge-base-in-three-weeks.md",
    }
    for item in SOURCE_DEFS:
        note = NOTES_BY_KEY[item["note_key"]]
        content = note["body_md"].replace("__KB_ID__", str(KB_ID))
        contents[item["key"]] = content
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        rows.append(
            {
                "id": SOURCE_ID[item["key"]],
                "kb_id": str(KB_ID),
                "type": item["type"],
                "title": item["title"],
                "raw_path": f"data/uploads/{KB_ID}/{filenames[item['key']]}",
                "sha256": sha,
                "status": "compiled",
                "parse_quality": "clean",
                "parse_engine": "native",
                "quality_report": {
                    "chars": len(content),
                    "lines": content.count("\n") + 1,
                    "encoding": "utf-8",
                    "warnings": [],
                },
                "scan_status": "heuristic",
                "scan_detail": "未配置 ClamAV；已通过内置启发式检查",
                "import_batch_id": None,
                "external_id": None,
                "source_url": "",
                "content_updated_at": None,
                "parsed_at": ts(41),
                "created_at": ts(40),
                "updated_at": ts(41),
            }
        )
    return rows, contents


def _note_rows() -> list[dict]:
    per_folder: dict[str, int] = {}
    rows = []
    for note in NOTES:
        body = note["body_md"].replace("__KB_ID__", str(KB_ID))
        props = dict(note["props"])
        props.pop("collection", None)
        source_id = SOURCE_ID.get(note["source_key"]) if note["source_key"] else None
        if note["kind"] == "import" and source_id:
            props["import"] = {
                "status": "ready",
                "filename": f"{SOURCE_BY_KEY[note['source_key']]['title']}.md",
                "progress": 1.0,
                "warnings": [],
                "source_id": source_id,
                "updated_at": ts(note["minutes"] + 1),
                "scan_detail": "未配置 ClamAV；已通过内置启发式检查",
                "scan_status": "heuristic",
                "title_source": "auto",
                "parse_quality": "clean",
            }
        index = per_folder.get(note["folder"], 0)
        per_folder[note["folder"]] = index + 1
        rows.append(
            {
                "id": note["id"],
                "kb_id": str(KB_ID),
                "title": note["title"],
                "body_md": body,
                "kind": note["kind"],
                "folder_id": FOLDER_ID[note["folder"]],
                "source_id": source_id,
                "status": "active",
                "view_mode": "edit",
                "sort_order": index,
                "props_json": props,
                "created_at": ts(note["minutes"]),
                "updated_at": ts(note["minutes"] + 3),
            }
        )
    return rows


def _collection_rows() -> tuple[list[dict], list[dict]]:
    collections: list[dict] = []
    row_rows: list[dict] = []
    for note in NOTES:
        database = DATABASES.get(note["key"])
        if database is None:
            continue
        collection_id = uid(f"collection:{note['key']}")
        collections.append(
            {
                "id": collection_id,
                "kb_id": str(KB_ID),
                "note_id": note["id"],
                "name": database["name"],
                "description": database["description"],
                "schema_json": {"fields": database["fields"]},
                "views_json": database["views"],
                "created_at": ts(note["minutes"]),
                "updated_at": ts(note["minutes"] + 1),
            }
        )
        for index, data in enumerate(database["rows"]):
            row_rows.append(
                {
                    "id": uid(f"row:{note['key']}:{index}"),
                    "kb_id": str(KB_ID),
                    "collection_id": collection_id,
                    "note_id": None,
                    "data": data,
                    "sort_order": index,
                    "created_at": ts(note["minutes"] + 1),
                    "updated_at": ts(note["minutes"] + 2),
                }
            )
    return collections, row_rows


WIKI_ID = {page["slug"]: uid(f"wiki:{page['slug']}") for page in WIKI_PAGES}
WIKI_BY_SLUG = {page["slug"]: page for page in WIKI_PAGES}

SOURCE_PAGES = {
    "cheatsheet": [
        "kiwi",
        "knowledge-base",
        "notes-workspace",
        "canvas",
        "database-views",
        "notebook",
        "import-pipeline",
        "link-notes",
        "wiki-compile",
        "bidirectional-links",
        "knowledge-graph",
        "study-mode",
        "spaced-repetition",
        "mock-exam",
        "study-profile",
        "tags-templates",
        "feature-cheatsheet",
    ],
    "project-brief": ["team-kb-in-three-weeks", "learning-loop"],
}


def _wiki_rows() -> tuple[list[dict], list[dict]]:
    pages = []
    for index, page in enumerate(WIKI_PAGES):
        sources = [SOURCE_ID[key] for key, slugs in SOURCE_PAGES.items() if page["slug"] in slugs]
        human_edited = page["slug"] in {"wiki-compile", "knowledge-graph"}
        pages.append(
            {
                "id": WIKI_ID[page["slug"]],
                "kb_id": str(KB_ID),
                "slug": page["slug"],
                "page_type": page["page_type"],
                "title": page["title"],
                "body_md": page["body"].strip(),
                "frontmatter_json": {
                    "type": page["page_type"],
                    "tags": [],
                    "sources": sources,
                },
                "compiled_from_source_ids": sources,
                "version": 3 if human_edited else 1,
                "human_edited": human_edited,
                "created_at": ts(60 + index),
                "updated_at": ts(190 + index),
            }
        )

    links = []
    seen: set[tuple[str, str]] = set()
    for source_slug, target_slug in WIKI_LINKS:
        if source_slug == target_slug:
            continue
        pair = (WIKI_ID[source_slug], WIKI_ID[target_slug])
        if pair in seen:
            continue
        seen.add(pair)
        links.append(
            {"from_page_id": pair[0], "to_page_id": pair[1], "link_type": "reference"}
        )
    return pages, links


NOTE_LINKS = _build_note_links()
SOURCE_ROWS, SOURCE_CONTENTS = _build_sources()
SOURCE_BY_KEY = {item["key"]: item for item in SOURCE_DEFS}
NOTE_COLLECTIONS, COLLECTION_ROWS = _collection_rows()
WIKI_ROWS, WIKI_LINKS_ROWS = _wiki_rows()


def _note_tag_links() -> list[dict]:
    rows = []
    for note in NOTES:
        for tag_key in note["tags"]:
            rows.append({"note_id": note["id"], "tag_id": TAG_ID[tag_key]})
    return rows


def _topic_rows() -> list[dict]:
    prerequisites = {
        "notes-workspace": ["knowledge-base"],
        "canvas": ["notes-workspace"],
        "database-views": ["notes-workspace"],
        "notebook": ["notes-workspace"],
        "import-pipeline": ["notes-workspace"],
        "link-notes": ["import-pipeline"],
        "wiki-compile": ["import-pipeline"],
        "bidirectional-links": ["wiki-compile"],
        "knowledge-graph": ["bidirectional-links"],
        "study-mode": ["knowledge-graph"],
        "spaced-repetition": ["study-mode"],
        "mock-exam": ["study-mode", "spaced-repetition"],
        "learning-loop": ["mock-exam", "knowledge-graph"],
    }
    rows = []
    for slug, title, mastery, weak, summary in TOPIC_DEFS:
        page = WIKI_BY_SLUG[slug]
        rows.append(
            {
                "id": uid(f"topic:{slug}"),
                "kb_id": str(KB_ID),
                "wiki_page_id": WIKI_ID[slug],
                "slug": slug,
                "title": title,
                "summary": summary,
                "domain": page["page_type"],
                "mastery_score": mastery,
                "sm2_state_json": {
                    "ease": 2.5,
                    "interval_days": 0,
                    "repetitions": 0,
                },
                "prerequisite_topic_ids": [
                    uid(f"topic:{item}") for item in prerequisites.get(slug, [])
                ],
                "weak_flag": weak,
                # 与 study_engine._content_hash 保持一致（sha1 + 落库时的 body_md）
                "content_hash": hashlib.sha1(page["body"].strip().encode("utf-8")).hexdigest(),
                "content_updated": False,
                "active": True,
                "created_at": ts(90),
                "updated_at": ts(190),
            }
        )
    return rows


def _attempt_rows() -> list[dict]:
    rows = []
    for session_key, question_key, correct, selected, answer, time_ms, minute in ATTEMPTS:
        question = QUESTION_BY_KEY[question_key]
        is_choice = question["type"] in ("single_choice", "true_false")
        rows.append(
            {
                "id": uid(f"attempt:{session_key}:{question_key}"),
                "kb_id": str(KB_ID),
                "session_id": SESSION_ID[session_key],
                "question_id": QUESTION_ID[question_key],
                "mock_exam_id": None,
                "correct": correct,
                "selected_index": selected if is_choice else -1,
                "user_answer": answer,
                "llm_score": None,
                "score_breakdown_json": {
                    "dimensions": [],
                    "selected_indexes": [selected] if is_choice else [],
                },
                "mode": next(item["mode"] for item in SESSIONS if item["key"] == session_key),
                "time_ms": time_ms,
                "attempted_at": ts(minute),
                "created_at": ts(minute),
                "updated_at": ts(minute),
            }
        )
    return rows


def _session_rows() -> list[dict]:
    return [
        {
            "id": SESSION_ID[item["key"]],
            "kb_id": str(KB_ID),
            "question_count": item["question_count"],
            "correct_count": item["correct_count"],
            "mode": item["mode"],
            "topic_slug": item["topic_slug"],
            "last_question_id": None,
            "status": item["status"],
            "finished_at": item["finished_at"],
            "created_at": item["created_at"],
            "updated_at": item["finished_at"],
        }
        for item in SESSIONS
    ]


def _review_rows() -> list[dict]:
    rows = []
    for slug, ease, interval, repetitions, due, reviewed, correct in REVIEWS:
        rows.append(
            {
                "id": uid(f"review:{slug}"),
                "kb_id": str(KB_ID),
                "wiki_page_id": WIKI_ID[slug],
                "slug": slug,
                "ease_factor": ease,
                "interval_days": interval,
                "repetitions": repetitions,
                "due_at": due,
                "last_reviewed_at": reviewed,
                "last_correct": correct,
                "created_at": ts(100),
                "updated_at": reviewed,
            }
        )
    return rows


def _annotation_rows() -> list[dict]:
    rows = []
    for index, item in enumerate(ANNOTATIONS):
        rows.append(
            {
                "id": uid(f"annotation:{item['target']}"),
                "kb_id": str(KB_ID),
                "target_type": "wiki",
                "target_id": WIKI_ID[item["target"]],
                "content_md": item["content_md"],
                "quote": item["quote"],
                "created_at": ts(180 + index),
                "updated_at": ts(180 + index),
            }
        )
    return rows


def build_seed() -> dict:
    folders = [
        {
            "id": FOLDER_ID[key],
            "kb_id": str(KB_ID),
            "name": name,
            "parent_id": None,
            "sort_order": order,
            "pinned": False,
            "created_at": ts(2),
            "updated_at": ts(2),
        }
        for key, name, order in FOLDERS
    ]
    tags = [
        {
            "id": TAG_ID[key],
            "kb_id": str(KB_ID),
            "name": name,
            "parent_id": None,
            "created_at": ts(3),
            "updated_at": ts(3),
        }
        for key, name in TAGS
    ]
    templates = [
        {
            "id": uid(f"template:{item['key']}"),
            "kb_id": str(KB_ID),
            "name": item["name"],
            "description": item["description"],
            "icon": item["icon"],
            "title_pattern": item["title_pattern"],
            "body_md": item["body_md"].strip(),
            "tags_json": item["tags"],
            "props_json": {},
            "is_builtin": False,
            "sort_order": index,
            "created_at": ts(5),
            "updated_at": ts(5),
        }
        for index, item in enumerate(TEMPLATES)
    ]
    notes = _note_rows()
    profile = {
        "id": PROFILE_ID,
        "kb_id": str(KB_ID),
        **PROFILE,
        "created_at": ts(80),
        "updated_at": ts(240),
    }
    return {
        "note_folders": folders,
        "note_tags": tags,
        "note_templates": templates,
        "sources": SOURCE_ROWS,
        "notes": notes,
        "note_collections": NOTE_COLLECTIONS,
        "collection_rows": COLLECTION_ROWS,
        "wiki_pages": WIKI_ROWS,
        "wiki_links": WIKI_LINKS_ROWS,
        "note_links": NOTE_LINKS,
        "note_tag_links": _note_tag_links(),
        "study_profiles": [profile],
        "learning_topics": _topic_rows(),
        "study_sessions": _session_rows(),
        "study_questions": QUESTIONS,
        "study_reviews": _review_rows(),
        "mock_exams": MOCK_EXAMS,
        "study_attempts": _attempt_rows(),
        "study_plans": STUDY_PLANS,
        "mock_exam_items": EXAM_ITEMS,
        "learning_annotations": _annotation_rows(),
    }


FEATURE_MAP_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="560" viewBox="0 0 1200 560" role="img" aria-label="Kiwi 功能全景">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0b1324"/><stop offset="0.55" stop-color="#111d33"/><stop offset="1" stop-color="#17233c"/>
    </linearGradient>
    <linearGradient id="flow" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#6ee7d0"/><stop offset="1" stop-color="#8ea7ff"/>
    </linearGradient>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect width="1200" height="560" rx="26" fill="url(#bg)"/>
  <g fill="#dce8ff" opacity="0.5">
    <circle cx="90" cy="120" r="1.4"/><circle cx="210" cy="70" r="1"/><circle cx="360" cy="130" r="1.2"/>
    <circle cx="520" cy="60" r="1"/><circle cx="700" cy="110" r="1.5"/><circle cx="860" cy="70" r="1"/>
    <circle cx="1010" cy="120" r="1.2"/><circle cx="1120" cy="80" r="1"/><circle cx="120" cy="470" r="1"/>
    <circle cx="300" cy="520" r="1.3"/><circle cx="520" cy="470" r="1"/><circle cx="760" cy="525" r="1.2"/>
    <circle cx="980" cy="480" r="1"/><circle cx="1130" cy="520" r="1.3"/>
  </g>
  <text x="60" y="76" fill="#f2f7ff" font-size="30" font-weight="700" font-family="'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif">Kiwi 功能全景</text>
  <text x="60" y="108" fill="#8fa3c8" font-size="15" font-family="'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif">一条内容如何走完「记录 → 连接 → 编译 → 学习 → 检验」的闭环</text>
  <g font-family="'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif">
    <g>
      <rect x="58" y="180" width="190" height="112" rx="16" fill="#16233c" stroke="#2c4266"/>
      <circle cx="88" cy="211" r="14" fill="#1d3b52" stroke="#5ad1c0"/>
      <text x="88" y="217" fill="#7ee7d6" font-size="14" text-anchor="middle" font-weight="700">1</text>
      <text x="114" y="217" fill="#eaf2ff" font-size="17" font-weight="700">记下来</text>
      <text x="80" y="247" fill="#93a9cc" font-size="12">文档 · 画布 · 数据表</text>
      <text x="80" y="269" fill="#93a9cc" font-size="12">Notebook · 导入 · 外链</text>
    </g>
    <g>
      <rect x="290" y="180" width="190" height="112" rx="16" fill="#16233c" stroke="#2c4266"/>
      <circle cx="320" cy="211" r="14" fill="#243a5c" stroke="#7ea6ff"/>
      <text x="320" y="217" fill="#a9c2ff" font-size="14" text-anchor="middle" font-weight="700">2</text>
      <text x="346" y="217" fill="#eaf2ff" font-size="17" font-weight="700">连起来</text>
      <text x="312" y="247" fill="#93a9cc" font-size="12">双向链接 · @ 提及</text>
      <text x="312" y="269" fill="#93a9cc" font-size="12">标签 · 目录树</text>
    </g>
    <g>
      <rect x="522" y="180" width="190" height="112" rx="16" fill="#16233c" stroke="#2c4266"/>
      <circle cx="552" cy="211" r="14" fill="#2a3358" stroke="#b39bff"/>
      <text x="552" y="217" fill="#c9b8ff" font-size="14" text-anchor="middle" font-weight="700">3</text>
      <text x="578" y="217" fill="#eaf2ff" font-size="17" font-weight="700">编译</text>
      <text x="544" y="247" fill="#93a9cc" font-size="12">素材 → Wiki 页面</text>
      <text x="544" y="269" fill="#93a9cc" font-size="12">来源 · 引用 · 人工校对</text>
    </g>
    <g>
      <rect x="754" y="180" width="190" height="112" rx="16" fill="#16233c" stroke="#2c4266"/>
      <circle cx="784" cy="211" r="14" fill="#3b3350" stroke="#ffc978"/>
      <text x="784" y="217" fill="#ffd79a" font-size="14" text-anchor="middle" font-weight="700">4</text>
      <text x="810" y="217" fill="#eaf2ff" font-size="17" font-weight="700">学习</text>
      <text x="776" y="247" fill="#93a9cc" font-size="12">画像 · 渐进训练</text>
      <text x="776" y="269" fill="#93a9cc" font-size="12">复习队列 · 批注</text>
    </g>
    <g>
      <rect x="986" y="180" width="156" height="112" rx="16" fill="#16233c" stroke="#2c4266"/>
      <circle cx="1016" cy="211" r="14" fill="#3d2b34" stroke="#ff9db4"/>
      <text x="1016" y="217" fill="#ffb3c6" font-size="14" text-anchor="middle" font-weight="700">5</text>
      <text x="1042" y="217" fill="#eaf2ff" font-size="17" font-weight="700">检验</text>
      <text x="1004" y="247" fill="#93a9cc" font-size="12">仿真考试</text>
      <text x="1004" y="269" fill="#93a9cc" font-size="12">评分 · 薄弱点</text>
    </g>
  </g>
  <g stroke="url(#flow)" stroke-width="2.4" fill="none" stroke-linecap="round">
    <path d="M250 236 H286" marker-end="url(#arrow)"/>
    <path d="M482 236 H518" marker-end="url(#arrow)"/>
    <path d="M714 236 H750" marker-end="url(#arrow)"/>
    <path d="M946 236 H982" marker-end="url(#arrow)"/>
    <path d="M1064 296 C1064 400 168 400 154 300" stroke-dasharray="7 7" opacity="0.75" marker-end="url(#arrow)"/>
  </g>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#8ea7ff"/>
    </marker>
  </defs>
  <g font-family="'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif">
    <text x="600" y="430" fill="#7f96bd" font-size="13" text-anchor="middle">闭环：考试暴露薄弱点 → 回到 Wiki 补链接 / 补内容 → 下一轮学习</text>
    <g transform="translate(168 452)">
      <rect width="864" height="58" rx="12" fill="#101a2d" stroke="#223353"/>
      <text x="26" y="24" fill="#8fa3c8" font-size="12">贯穿能力</text>
      <text x="26" y="44" fill="#dbe7ff" font-size="13">知识图谱（星图 / 精要 / 掌握度） · 全文检索 · AI 问答（带来源） · 学习计划 · 备份与还原</text>
    </g>
  </g>
</svg>
"""


def _write_assets() -> None:
    for key, content in SOURCE_CONTENTS.items():
        filename = {
            "cheatsheet": "kiwi-feature-cheatsheet.md",
            "project-brief": "team-knowledge-base-in-three-weeks.md",
        }[key]
        target = UPLOADS / str(KB_ID) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    media = MEDIA / str(KB_ID) / "kiwi-feature-map.svg"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_text(FEATURE_MAP_SVG, encoding="utf-8")


def _validate() -> None:
    problems: list[str] = []
    note_titles = {note["title"] for note in NOTES}
    wiki_titles = {page["title"] for page in WIKI_PAGES}
    wiki_keys = wiki_titles | {page["slug"] for page in WIKI_PAGES}
    for page in WIKI_PAGES:
        for match in LINK_RE.finditer(_prose(page["body"])):
            target = match.group(1).strip()
            if target not in wiki_keys:
                problems.append(f"Wiki「{page['title']}」引用了不存在的页面：{target}")
    for slug, _ in WIKI_LINKS:
        if slug not in WIKI_BY_SLUG:
            problems.append(f"WIKI_LINKS 起点不存在：{slug}")
    for _, slug in WIKI_LINKS:
        if slug not in WIKI_BY_SLUG:
            problems.append(f"WIKI_LINKS 终点不存在：{slug}")
    for note in NOTES:
        if note["kind"] not in {"doc", "canvas", "database", "notebook", "import", "link"}:
            problems.append(f"未知笔记类型：{note['key']} → {note['kind']}")
    if len({note["title"] for note in NOTES}) != len(NOTES):
        problems.append("笔记标题不唯一：旧格式 [[标题]] 会无法区分目标")
    note_ids = {note["id"] for note in NOTES}
    for note in NOTES:
        for match in NOTE_MENTION_RE.finditer(_prose(note["body_md"])):
            if match.group(1) not in note_ids:
                problems.append(
                    f"笔记「{note['title']}」的 @ 提及指向不存在的笔记：{match.group(1)}"
                )
    # 教程里 `[[标题]]` 之类是语法示意，不做未解析告警
    placeholders = {"标题", "相关笔记", "相关知识点", "另一篇笔记"}
    unresolved = {
        match.group(1).strip()
        for note in NOTES
        for match in LINK_RE.finditer(_prose(note["body_md"]))
        if match.group(1).strip() not in note_titles
        and match.group(1).strip() not in wiki_titles
        and match.group(1).strip() not in placeholders
    }
    if unresolved:
        problems.append("笔记中存在无法解析的链接：" + "、".join(sorted(unresolved)))
    if problems:
        raise SystemExit("seed 校验失败：\n- " + "\n- ".join(problems))

    print(f"笔记 {len(NOTES)} 篇 · 笔记链接 {len(NOTE_LINKS)} 条 · Wiki 页面 {len(WIKI_PAGES)} 页")
    print(f"素材 {len(SOURCE_ROWS)} 份 · 数据表行 {len(COLLECTION_ROWS)} 行 · 题目 {len(QUESTIONS)} 道")
    print(f"考试 1 场（{EXAM_BREAKDOWN['total']}/100） · 复习 {len(REVIEWS)} 条 · 批注 {len(ANNOTATIONS)} 条")


def main() -> None:
    _validate()

    # 组装阶段会临时把 collection 挂在 note 上
    data = build_seed()
    SEED_FILE = ASSETS / "demo_seed.json"
    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_assets()
    print(f"已写入 {SEED_FILE}（{SEED_FILE.stat().st_size / 1024:.1f} KB）")
    print(f"素材目录：{UPLOADS / str(KB_ID)}")


if __name__ == "__main__":
    main()
