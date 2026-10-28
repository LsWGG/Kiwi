<p align="center">
  <img src="docs/assets/screenshots/notebook.png" alt="Kiwi Notebook 图形化分析" width="920" />
</p>

<h1 align="center">Kiwi · 知识编译与学习系统</h1>

<p align="center">
  把笔记编译成知识，把知识变成掌握度。<br />
  <a href="https://lswgg.github.io/Kiwi/">产品主页</a> · <strong>简体中文</strong> · <a href="README.md">English</a>
</p>

<p align="center">
  <img alt="Vue 3.5" src="https://img.shields.io/badge/Vue-3.5-42b883?logo=vuedotjs&logoColor=white" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5.x-3178c6?logo=typescript&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.143-009688?logo=fastapi&logoColor=white" />
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169e1?logo=postgresql&logoColor=white" />
  <img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-1.19-dc244c" />
  <img alt="Local first" src="https://img.shields.io/badge/local--first-single--user-6f72dc" />
</p>

---

Kiwi 不是另一个「把东西存起来」的笔记软件。

文档、PDF、网页、数据表、画布与 Notebook 在这里是原材料：编译流水线把它们拆成概念、合并成相互引用的 Wiki 页面，并为每一条结论保留来源。随后，同一份知识进入学习引擎——画像、训练、间隔重复、仿真考试，掌握度再回写到页面。

大多数工具在「记下来」处结束。Kiwi 继续追问：**你怎么知道自己真的学会了？**

## 为什么不同

- **知识是编译出来的。** 不靠手工维护目录，而由 Schema、增量编译与引用关系让结构自己长出来。
- **图谱也是掌握度地图。** 页面引用、笔记关联、薄弱点与掌握度共用一套坐标；既看知识怎么连，也看哪里还没学会。
- **学习闭环长在知识库里。** 出题、复习、考试与掌握度更新都在库内完成，不需要把内容导出到另一个工具。
- **本地优先，模型可替换。** PostgreSQL + Qdrant 单机运行，兼容任意 OpenAI 协议模型；数据与推理都留在自己的机器上。

## 核心能力

- **笔记工作区**：文档、数据表、表格、导入、外链、画布、Notebook 共用目录、标签、模板与双向链接。
- **两种编辑模式**：同一份 Markdown 在标准编辑与 DOCX 间切换——块级写作、交互区块与正式排版各取所需。
- **可执行代码块**：Python 在 bubblewrap 沙箱中运行，输出与退出码以块的形式留在正文；HTML / JS 在隔离 iframe 中预览。
- **进阶能力**：语音转写、贴一贴浮窗、组件插件、只读分享、表格与 OCR、混合检索问答、待办汇总与按类型导出。
- **编译任务**：全部可编译笔记统一编译进 Wiki，待办汇总、只读导入与数据表行笔记自动跳过，并追踪任务进度与受影响页面。
- **结构化 Wiki**：Schema 驱动、增量更新、来源引用、健康检查与一键重建。
- **知识星图**：星图式浏览页面关系，节点大小反映被引次数。
- **学习闭环**：画像 → 计划 → 渐进练习 → 间隔重复 → 仿真考试 → 错题本。
- **有出处的问答**：检索 Wiki 与笔记，支持会话历史与行内引用，回答可溯源，也可回写为新页面。

## 界面

<table>
  <tr>
    <th width="50%" align="left">编辑模式 · 编译与组织</th>
    <th width="50%" align="left">学习模式 · 练习与检验</th>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/wiki-page-basic.png" alt="结构化 Wiki" /><br /><sub>结构化 Wiki：目录、大纲与反向链接</sub></td>
    <td><img src="docs/assets/screenshots/learn-plan.png" alt="学习计划" /><br /><sub>学习计划：按掌握度动态排程</sub></td>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/notes-welcome.png" alt="笔记工作区" /><br /><sub>笔记工作区：目录树、双链与上手引导</sub></td>
    <td><img src="docs/assets/screenshots/exam-report.png" alt="仿真考试报告" /><br /><sub>仿真考试：分卷表现与知识点雷达</sub></td>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/wiki-graph.png" alt="知识星图" /><br /><sub>知识星图：概念关系与被引次数</sub></td>
    <td><img src="docs/assets/screenshots/learn-graph.png" alt="学习图谱" /><br /><sub>学习图谱：掌握度分布与薄弱点</sub></td>
  </tr>
</table>

## 技术栈

Vue 3.5 · TypeScript · Vite · Pinia · Tailwind CSS · TipTap · AntV G6  
FastAPI · SQLAlchemy 2 · PostgreSQL 16 · Qdrant · fastembed  
Docker Compose · uv · Node.js

## 启动

需要 Python 3.12、uv、Node.js ≥ 20 与 Docker：

```bash
git clone https://github.com/LsWGG/Kiwi.git
cd Kiwi
./run.sh
```

访问 http://localhost:5173 默认进入产品门户；应用工作区位于 http://localhost:5173/kbs，在设置中填写任意 OpenAI 兼容模型即可使用。若运行环境无法加载本地向量模型，可在 **设置 → 向量模型** 切换为线上 embedding 接口。

首次启动会注入内置的 **「Kiwi 上手指南 · 功能演示知识库」**，包含 22 篇笔记、29 个 Wiki 页面以及完整的学习与考试数据，可自由修改、删除或还原。

## Windows 桌面版（可选）

独立窗口（WebView2）安装包把同一套应用与 PostgreSQL、Qdrant、便携 Python 一起交付。不内置任何大模型、向量模型、Whisper 或 OCR 模型，数据默认只留在本机；配置本机或 OpenAI 兼容接口后才启用 AI 功能。Docker 仍是主线部署方式。

从 Releases 下载 `Kiwi-Setup-<version>.exe`，或在 Windows 10/11 x64 上构建：

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Version 1.0.0
```

安装、离线边界、本机代码执行、备份恢复与故障排查见 [docs/WINDOWS.md](docs/WINDOWS.md)。

## Docker 部署

生产环境使用独立的 Compose 文件，默认全部采用非常规端口：Web `18473`、API `18474`、PostgreSQL `15432`、Qdrant `16333 / 16334`。

前端在宿主机完成构建，并以只读方式挂载进 nginx，Docker 镜像构建阶段不再执行 npm / Vite：

```bash
(cd frontend && npm ci && npm run build)
./deploy.sh
```

`./deploy.sh` 负责构建后端镜像并执行数据库迁移；`./deploy.sh frontend` 只重新构建静态产物。前端改动后重新生成 `frontend/dist` 并刷新浏览器即可，无需重建容器。访问 `http://<host>:18473` 即可。

端口调整、数据备份、升级、沙箱权限与排障见 [docs/DEPLOY.md](docs/DEPLOY.md)。版本演进见 [版本迭代记录](docs/CHANGELOG.md)，后续计划见 [迭代计划](docs/ROADMAP.md)。

## 测试

```bash
# 后端：纯逻辑与 API 契约测试（真实 PostgreSQL / Qdrant）
cd backend && uv run pytest -q

# 前端类型检查与 Playwright 冒烟测试
cd frontend && npm run type-check && npm run test:e2e
```

Playwright 默认连接 `http://127.0.0.1:8000`，建议使用隔离测试库并关闭后台 worker 与限流（`KIWI_BACKGROUND_JOBS=false`、`KIWI_RATE_LIMIT_ENABLED=false`）。额外设置 `PW_TOKEN_BACKEND_URL` 与 `PW_ACCESS_TOKEN` 可运行访问令牌登录用例。CI 会在每次推送与 PR 上执行完整测试。

---

## 版权与许可

Copyright © 2026 LsWGG。

Kiwi 是自由软件：你可以依据自由软件基金会发布的 GNU Affero 通用公共许可证第 3 版（SPDX: AGPL-3.0-only）重新分发和/或修改本项目。

Kiwi 按“现状”分发，不附带任何明示或暗示的担保，包括但不限于适销性或特定用途适用性的担保。完整许可证文本见 [LICENSE](LICENSE)。

由于安装包包含以 AGPL-3.0 授权的 PyMuPDF，分发版本整体按 AGPL-3.0 提供。对应源代码见 <https://github.com/LsWGG/Kiwi>，第三方组件声明见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
