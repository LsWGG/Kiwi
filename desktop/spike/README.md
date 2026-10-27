# Windows 可行性 Spike（Phase 0）

对应 `harmonic-plotting-seal.md` 的 Phase 0：在 GitHub Actions 的 `windows-latest`
（真实 Windows Server）上验证桌面版打包所依赖的组件，避免在 Linux 上靠猜测推进。

## 运行方式

推送到 `feat/windows-desktop-spike` 分支（改动 `desktop/spike/**` 或本工作流时），
或在 Actions 页面手动触发 `Windows 可行性 Spike`。

工作流用 `permissions: contents: write` 的书签作业把每个任务的 JSON 结果提交回
`desktop/spike/out/`（提交信息带 `[skip ci]`），因此无需登录 Actions 也能查看结论。

## 检查项

| Job | 验证内容 | 退出标准 |
| --- | --- | --- |
| `pgserver` | pgserver 0.1.4 启动、URI、建表写入、`pg_dump`、重启持久化、含中文与空格的数据目录 | 决定用 pgserver 还是自带 PostgreSQL 16 二进制 |
| `qdrant` | Qdrant 1.20.0 Windows 二进制下载、loopback 监听、`/readyz`、集合读写、中文 payload | 确认 Windows 发布包可用 |
| `portable-python` | python-build-standalone 3.12.16 下载解压、numpy / pandas / matplotlib / openpyxl / pillow 实际使用 | 确认本机代码执行运行时可用 |
| `pyinstaller` | 冻结 FastAPI / uvicorn / SQLAlchemy / asyncpg / alembic / qdrant-client / openai，启动本地 HTTP 服务 | 确认 PyInstaller onedir 路线可行 |
| `job-object` | `KILL_ON_JOB_CLOSE`、进程树终止、挂起创建后加入 Job 再恢复 | 确认 Windows 本机执行能可靠清理进程 |
| `webview2` | .NET 10 WinForms 自包含发布、`CoreWebView2Environment` 与注册表检测 Evergreen 运行时 | 决定 Evergreen 还是 Fixed Version |
| `backend-deps` | `uv sync --frozen` 在 Windows 安装全部后端依赖并导入 `app.main` | 确认后端本身可在 Windows 运行 |

## 尚未覆盖

- **CSP 兼容性**（`srcdoc` 预览、PDF.js、Mermaid）依赖实际前端与 WebView2 窗口，
  留到 Phase 5/6 提供 SPA 后再用 WebView2 探针验证。
- 真实窗口、DPI、单实例、安装器静默安装等 GUI 验收仍需 Windows 10/11 机器手工执行。

## 结果文件

- `out/summary.json` / `out/SUMMARY.md`：各 Job 状态与关键结论。
- `out/<job>.json`：单个任务的步骤耗时、版本、错误堆栈。
- 原始日志只留在 Actions artifact，不提交到仓库（避免包含临时连接信息）。
