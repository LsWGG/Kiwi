"""LLM Wiki Schema：每个知识库一份独立、可迭代的结构化规范文件。

README 设计要点：Schema 是 LLM Wiki 区别于普通 RAG 的关键——用一份独立的
结构化文件定义页面类型与模板、slug / wikilink 规范、质量标准与 ingest 指令。
编译时把整份 Schema 注入 LLM 上下文；用户可在 Wiki 设置中查看、修改、重置。

文件落盘在 ``<upload_dir>/../wiki_schemas/<kb_id>.md``（即 backend/data/wiki_schemas），
不进入数据库，便于用户直接编辑与版本管理。
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import uuid
from pathlib import Path

from app.config import settings

MAX_SCHEMA_CHARS = 100_000

DEFAULT_WIKI_SCHEMA = """# Kiwi LLM Wiki Schema（v1）

本文件定义本知识库 Wiki 的页面类型、写作模板、链接规范、质量标准与编译指令。
编译引擎会把整份 Schema 注入 LLM 上下文，请用平实、明确、可执行的语言修改。

## 1. 页面类型与模板

### entity（实体）
用于具体可命名的人、组织、产品、项目、标准、法规、工具、事件等。
模板：
```
# {title}
> 一句话定义。

## 基本信息
| 属性 | 内容 |
| --- | --- |
| 类型 | … |
| 别名 | … |

## 核心事实
- 只写材料明确支持的内容，每条尽量可回溯来源。

## 与其它页面的关系
- [[related-slug]] — 关系说明（包含 / 依赖 / 对比 / 属于）。

## 来源
- {素材标题} · {章节或分块}
```

### concept（概念）
用于抽象概念、方法论、原理、术语、流程与机制。
模板：
```
# {title}
> 一句话定义。

## 定义与边界
## 关键要点
## 适用场景与限制
## 常见误解
## 与其它页面的关系
- [[related-slug]] — 关系说明
## 来源
- {素材标题} · {章节或分块}
```

### summary（摘要）
用于对单篇素材或单一主题的结构化摘要，保留原文脉络。
模板：概述 → 主要论点 → 关键数据 → 结论 → 关联页面 → 来源。

### synthesis（综合）
用于跨来源对比、归纳、结论或争议梳理；必须列出所综合的来源。
模板：问题 → 各来源观点 → 对比表 → 结论 → 未决问题 → 来源。

## 2. slug 与 wikilink 规范

- slug 必须唯一：小写，使用短横线 `-` 分词，保留必要的中文（如 `数据治理`），不超过 120 字符。
- 不使用空格、`_`、`/`、`#`、`?`；不使用纯数字。
- wikilink 一律指向 slug：`[[data-governance]]`，不要用页面标题或 URL。
- 每个页面至少 2 个外出 wikilink，且至少被 1 个其它页面引用（新建孤页时应主动补链）。
- 不链接自身；同一目标不重复链接。
- 关系类型不要写进链接本身，在链接后用一句话说明关系。

## 3. 质量标准

- 最少交叉引用数：2
- 来源标注：每个事实性小节末尾用 `> 来源：{素材标题} · {章节}` 标注；页面末节保留来源列表。
- 每条关键结论必须能在来源中找到依据；没有依据的内容必须标注 `> ❓待核实：…`。
- 矛盾标记：`> ⚠️ 矛盾：A 来源称……，B 来源称……`，并在 synthesis 页汇总。
- 不编造数字、日期、法规条款、人名与引文；引用原文时使用引号并注明出处。
- human_edited=true 的页面受保护，编译不得覆盖，只能在源漂移时提示。
- 新增或更新页面后要保证原有 wikilink 仍然有效；slug 变更必须同步所有入链。

## 4. ingest 指令

1. 读取新素材的全部分块，识别核心主题、实体、概念与结论。
2. 检索本库已有关联页面（标题 + 语义相关正文），判断每个主题应更新已有页还是新建页。
3. 更新已有页时写增量补充段，保留既有结构与来源；新建页时套用对应页面类型模板。
4. 维护 wikilink 网络：新页链接到相关旧页，相关旧页补充指向新页。
5. 对跨来源的对比、冲突或综合结论，维护一页 synthesis。
6. 输出 JSON：create / update 列表；不输出解释性文字。
"""


def schema_dir() -> Path:
    """Schema 存放目录（跟随上传目录的数据根）。"""
    return Path(settings.upload_dir).parent / "wiki_schemas"


def schema_path(kb_id: uuid.UUID | str) -> Path:
    return schema_dir() / f"{kb_id}.md"


def load_schema(kb_id: uuid.UUID | str) -> tuple[str, bool]:
    """读取知识库 Schema，返回 (content, customized)。

    文件缺失或不可读时回退到内置默认 Schema，保证编译始终有规范可用。
    """
    path = schema_path(kb_id)
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return DEFAULT_WIKI_SCHEMA, False
    if not content.strip():
        return DEFAULT_WIKI_SCHEMA, False
    return content, True


def save_schema(kb_id: uuid.UUID | str, content: str) -> str:
    """原子写入 Schema 文件；返回规范化后的内容。"""
    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        raise ValueError("Schema 不能为空；如需恢复默认请使用重置。")
    if len(normalized) > MAX_SCHEMA_CHARS:
        raise ValueError(f"Schema 过长（最多 {MAX_SCHEMA_CHARS} 字符）。")

    directory = schema_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{kb_id}-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(normalized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, schema_path(kb_id))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return normalized


def reset_schema(kb_id: uuid.UUID | str) -> None:
    """删除自定义 Schema，回到内置默认。"""
    try:
        schema_path(kb_id).unlink()
    except FileNotFoundError:
        pass
