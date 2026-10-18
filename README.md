<p align="center">
  <img src="docs/assets/screenshots/kb-manager.png" alt="Kiwi 知识库管理" width="920" />
</p>

<h1 align="center">Kiwi · 知识编译与学习系统</h1>

<p align="center">
  把零散笔记与素材，编译成一张可以阅读、追问、练习和复习的知识网络。
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

Kiwi 是一个本地优先的个人知识库系统。文档、PDF、网页、数据表、画布和 Notebook 先成为可编辑的**笔记**；再由编译流水线抽取概念、合并页面、建立引用，长成结构化的 **Wiki**；最后交给学习模式，生成学习计划、练习题、间隔复习和仿真考试。

它想解决的不只是「知识存在哪里」，而是知识如何被**读懂、连接、练习和记住**。

## 核心功能

- **笔记工作区**：文档、数据表、导入、外链、画布、Notebook 共用目录、标签、模板与双向链接。
- **编译任务**：所有笔记和素材统一编译进 Wiki，追踪解析质量、任务进度与受影响页面。
- **结构化 Wiki**：Schema 驱动的页面生成、增量更新、引用图谱、健康检查与一键重建。
- **知识图谱**：星图式浏览页面关系，节点大小反映被引次数。
- **学习闭环**：学习画像 → 计划 → 渐进练习 → 间隔重复 → 仿真考试 → 错题本。
- **有出处的问答**：基于笔记与 Wiki 的混合检索，回答可溯源，也可回写为 Wiki 页面。
- **本地优先**：PostgreSQL + Qdrant，兼容任意 OpenAI 协议模型（Ollama 或云端）。

## 界面

<table>
  <tr>
    <td width="50%"><img src="docs/assets/screenshots/notes-doc.png" alt="笔记工作区" /><br /><sub>笔记工作区</sub></td>
    <td width="50%"><img src="docs/assets/screenshots/compile-jobs.png" alt="编译任务" /><br /><sub>编译任务</sub></td>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/wiki-graph.png" alt="知识图谱" /><br /><sub>知识图谱</sub></td>
    <td><img src="docs/assets/screenshots/canvas.png" alt="画布" /><br /><sub>画布</sub></td>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/database-progress.png" alt="数据表" /><br /><sub>数据表</sub></td>
    <td><img src="docs/assets/screenshots/learn-graph.png" alt="学习模式" /><br /><sub>学习模式</sub></td>
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

访问 http://localhost:5173，在设置中填写任意 OpenAI 兼容模型即可使用。

首次启动会注入内置的 **「Kiwi 上手指南 · 功能演示知识库」**，包含 22 篇笔记、29 个 Wiki 页面以及完整的学习与考试数据，可自由修改、删除或还原。

更多设计细节见 [docs/design/kiwi-design-v1.2.md](docs/design/kiwi-design-v1.2.md)。
