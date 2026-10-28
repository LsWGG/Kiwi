# Kiwi Windows 桌面版（开发说明）

用户文档见 [docs/WINDOWS.md](../docs/WINDOWS.md)。

## 目录

```
desktop/
  Kiwi.Desktop/          .NET 10 WinForms + WebView2 宿主
  runtime/               PyInstaller 入口、离线审计与便携 Python sitecustomize
  installer/kiwi.iss     Inno Setup 安装脚本
  scripts/               桌面前端离线扫描
  spike/                 Phase 0 Windows 可行性验证（已归档）
  build.ps1 / build.cmd  一键打包
  versions.json          第三方组件版本与 SHA-256
  requirements-build.txt PyInstaller / pgserver（仅构建期）
  requirements-runner.txt 便携 Python 的本机执行包
```

## 本地开发

桌面模式等价于在现有后端上打开一组开关：

```bash
KIWI_DESKTOP_MODE=true \
KIWI_OFFLINE_MODE=true \
KIWI_FRONTEND_DIST=$PWD/frontend/dist \
KIWI_DESKTOP_SETTINGS_PATH=$PWD/backend/data/desktop-settings.json \
KIWI_EMBED_PROVIDER=none \
uv run --project backend uvicorn app.main:app --port 8000
```

前端使用 `npm run build:desktop`（Linux 上可构建与验证离线产物），或在
`frontend` 下以 `--mode desktop` 启动 Vite。宿主窗口本身只能在 Windows 上运行。

## 构建顺序

`build.ps1` 依次执行：

1. 检查 Python 3.12 / uv / Node / .NET 10 / Inno Setup（`-Bootstrap` 可自动安装）；
2. `npm ci` + `npm run build:desktop`，并扫描产物中的远程主机；
3. `uv sync --frozen --extra dev` + `uv pip install -r requirements-build.txt`，
   运行 `ruff` / `pytest`（`-SkipTests` 跳过），再调用 PyInstaller；
4. 从 `versions.json` 下载并校验 Qdrant、便携 Python（固定 SHA-256）与 WebView2
   Evergreen 安装程序（微软 fwlink 内容随更新变化，不校验哈希），安装运行包；
5. `dotnet publish` 发布 self-contained 宿主到暂存目录；
6. 用 Inno Setup 生成安装包与 `.sha256`。

产物在 `desktop/dist`，暂存目录在 `desktop/build/app`。第三方下载缓存于
`desktop/.cache`（已 gitignore）。`-SkipDownloads` 可在离线环境复用缓存。

## 冒烟

安装后运行：

```powershell
& "$env:LOCALAPPDATA\Programs\Kiwi\Kiwi.Desktop.exe" --smoke-test
```

它会启动真实 runtime（PostgreSQL / Qdrant / migrations / API），验证 SPA、深链接、
桌面状态、笔记创建与搜索、同步备份和内部关闭；结果写入
`%LOCALAPPDATA%\Kiwi\logs\smoke-test.log`，退出码 0/1。该模式不创建 WebView2 窗口。

Windows 专项测试：

```powershell
cd backend
$env:KIWI_TEST_DATABASE_URL = "postgresql+asyncpg://kiwi:kiwi@localhost:5432/kiwi_test"
uv run pytest -q tests/test_windows_runner.py
```

## 修改桌面行为时的约束

- 所有桌面分支必须由 `settings.desktop_mode` / `IS_DESKTOP` 控制，默认值保持
  Docker 现有行为；
- 不新增数据库迁移；桌面设置存 JSON；
- 新增联网功能时同时在 `desktop_guard`、桌面能力表与前端空态中登记；
- 不要在本机执行子进程中传递 `KIWI_*`、数据库 URL、Fernet 密钥或控制令牌；
- 第三方版本升级必须更新 `versions.json` 的 URL、版本与 SHA-256，并重新跑 Windows
  冒烟。
