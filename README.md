<p align="center">
  <img src="docs/assets/screenshots/notebook.png" alt="Kiwi Notebook graphical analysis" width="920" />
</p>

<h1 align="center">Kiwi · Knowledge Compilation &amp; Learning System</h1>

<p align="center">
  Compile notes into knowledge. Turn knowledge into mastery.<br />
  <a href="https://lswgg.github.io/Kiwi/">Product site</a> · <a href="README.zh-CN.md">简体中文</a> · <strong>English</strong>
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

Kiwi is not another note-taking app that stops at storing things.

Documents, PDFs, web pages, spreadsheets, canvases, and notebooks are raw material here. A compilation pipeline breaks them into concepts, merges them into cross-referenced Wiki pages, and preserves the source behind every conclusion. The same knowledge then enters the learning engine—profile, practice, spaced repetition, mock exams—and mastery is written back to the pages.

Most tools stop at “captured.” Kiwi keeps asking: **How do you know you have actually learned it?**

## Why it is different

- **Knowledge is compiled.** No hand-maintained hierarchy. Schema, incremental compilation, and references let structure grow on its own.
- **The graph is also a mastery map.** Page references, note links, weak spots, and mastery share one coordinate system—see how knowledge connects and where you have not learned it yet.
- **The learning loop lives inside the knowledge base.** Questions, review, exams, and mastery updates all happen in the same library; no exporting content to another tool.
- **Local-first, swappable models.** Runs on a single machine with PostgreSQL + Qdrant and supports any OpenAI-compatible model; data and inference stay on your hardware.

## Core capabilities

- **Note workspace**: docs, databases, imports, links, canvas, and notebooks share folders, tags, templates, and bidirectional links.
- **Three editing modes**: switch the same Markdown between Simple, Notion-like, and DOCX editors—focused writing, block-level organization, and formal layout each get the right tool.
- **Executable code blocks**: Python runs in a bubblewrap sandbox, with output and exit code kept in the document; HTML / JS previews inside an isolated iframe.
- **Compilation jobs**: every note and source compiles into the Wiki, with parse quality, job progress, and affected pages tracked.
- **Structured Wiki**: schema-driven, incrementally updated, source-cited, with health checks and one-click rebuild.
- **Knowledge star map**: explore page relationships as a star map; node size reflects citation count.
- **Learning loop**: profile → plan → progressive practice → spaced repetition → mock exam → mistake notebook.
- **Answers with sources**: hybrid retrieval across the Wiki and raw notes; answers are traceable and can be saved as new pages.

## Interface

<table>
  <tr>
    <th width="50%" align="left">Editing · Compile and organize</th>
    <th width="50%" align="left">Learning · Practice and assess</th>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/wiki-page-basic.png" alt="Structured Wiki" /><br /><sub>Structured Wiki: contents, outline, and backlinks</sub></td>
    <td><img src="docs/assets/screenshots/learn-plan.png" alt="Learning plan" /><br /><sub>Learning plan: dynamically scheduled by mastery</sub></td>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/notes-welcome.png" alt="Note workspace" /><br /><sub>Note workspace: tree, wikilinks, and onboarding</sub></td>
    <td><img src="docs/assets/screenshots/exam-report.png" alt="Mock exam report" /><br /><sub>Mock exam: section performance and knowledge radar</sub></td>
  </tr>
  <tr>
    <td><img src="docs/assets/screenshots/wiki-graph.png" alt="Knowledge star map" /><br /><sub>Knowledge star map: concept relationships and citations</sub></td>
    <td><img src="docs/assets/screenshots/learn-graph.png" alt="Learning graph" /><br /><sub>Learning graph: mastery distribution and weak spots</sub></td>
  </tr>
</table>

## Tech stack

Vue 3.5 · TypeScript · Vite · Pinia · Tailwind CSS · TipTap · AntV G6  
FastAPI · SQLAlchemy 2 · PostgreSQL 16 · Qdrant · fastembed  
Docker Compose · uv · Node.js

## Getting started

Requires Python 3.12, uv, Node.js ≥ 20, and Docker:

```bash
git clone https://github.com/LsWGG/Kiwi.git
cd Kiwi
./run.sh
```

<http://localhost:5173> opens the product portal by default; the app workspace is at <http://localhost:5173/kbs>. Add any OpenAI-compatible model in Settings to start. If local embedding models cannot load in your environment, switch to a hosted embedding API under **Settings → Embedding model**.

On first launch, Kiwi seeds the built-in **“Kiwi Quick Start · Feature Demo”** knowledge base, containing 22 notes, 29 Wiki pages, and complete learning and exam data. You can edit, delete, or restore it at any time.

## Docker deployment

Production uses a separate Compose file with non-standard ports by default: Web `18473`, API `18474`, PostgreSQL `15432`, Qdrant `16333 / 16334`.

The frontend is built on the host and mounted read-only into nginx — the Docker image no longer runs npm or Vite:

```bash
(cd frontend && npm ci && npm run build)
./deploy.sh
```

`./deploy.sh` builds the backend image and runs database migrations; `./deploy.sh frontend` rebuilds the static bundle only. Rebuild `frontend/dist` and refresh the browser after frontend changes — no container rebuild is needed. Then open `http://<host>:18473`.

See [docs/DEPLOY.md](docs/DEPLOY.md) for port changes, backups, upgrades, sandbox permissions, and troubleshooting. See the [changelog](docs/CHANGELOG.md) for releases.

---

## Copyright

Copyright © 2026 LsWGG. All rights reserved.

No part of this project may be copied, modified, distributed, or used commercially without permission. See [LICENSE](LICENSE) for the full terms.
