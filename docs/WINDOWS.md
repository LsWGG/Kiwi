# Windows 桌面版

Kiwi 桌面版把同一套前端与后端打包成独立窗口应用（.NET 10 + WebView2），
PostgreSQL、Qdrant 与可选的本机代码执行环境全部随包携带，数据默认只留在本机。
Docker / Web 仍是主线部署方式；桌面版由独立开关启用，不改变现有部署行为。

- **支持**：Windows 10 22H2（10.0.19045）及以上、Windows 11，x64。
- **不支持**：Windows ARM64、Windows 7/8、自动更新、托盘常驻、内置模型。
- **安装方式**：当前用户安装，不需要管理员权限；默认目录
  `%LOCALAPPDATA%\Programs\Kiwi`。
- **用户数据**：`%LOCALAPPDATA%\Kiwi`，卸载不删除。

> 桌面版**不内置任何 LLM / 向量 / Whisper / OCR 模型**。未配置模型时，
> 笔记、检索（PostgreSQL 关键词搜索）、Wiki 浏览、学习复习等本地功能正常可用；
> 问答、向量检索、Wiki 自动编译、学习出题等 AI 功能显示「未配置模型」。

## 安装

1. 运行 `Kiwi-Setup-<version>.exe`。安装器只写入当前用户目录，不请求提权。
2. 若系统缺少 WebView2 Runtime，安装器会静默运行随包的 Evergreen 安装程序。
   企业策略禁止安装时，可改用携带 Fixed Version 运行时的构建，或先手动安装
   [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
3. 从开始菜单或桌面快捷方式启动「Kiwi」。首次启动会初始化数据库与内置演示库，
   通常需要十几秒；启动页会显示 `postgres → qdrant → migrate → http → ready` 阶段。

安装包未做代码签名时，Windows SmartScreen 可能提示「未知发布者」。请核对
发布页提供的 SHA-256 后再运行：

```powershell
Get-FileHash .\Kiwi-Setup-1.0.0.exe -Algorithm SHA256
```

### 升级与卸载

- **升级**：直接运行新版本安装包，安装到同一目录，数据与设置保留。
- **卸载**：设置 → 应用 → Kiwi → 卸载。只删除程序文件，保留
  `%LOCALAPPDATA%\Kiwi`。需要彻底清除时，手动删除该目录（不可恢复）。

## 数据目录

| 路径 | 内容 |
|---|---|
| `%LOCALAPPDATA%\Kiwi\pg` | PostgreSQL 数据文件 |
| `%LOCALAPPDATA%\Kiwi\qdrant` | Qdrant 向量存储（未配置 embedding 时为空） |
| `%LOCALAPPDATA%\Kiwi\uploads` | 导入素材与附件 |
| `%LOCALAPPDATA%\Kiwi\backups` | 自动 / 手动备份 |
| `%LOCALAPPDATA%\Kiwi\notebooks` | Notebook 内核工作目录 |
| `%LOCALAPPDATA%\Kiwi\sandbox` | 代码块临时运行目录 |
| `%LOCALAPPDATA%\Kiwi\secrets\fernet.key` | 模型 API Key 的本地加密密钥 |
| `%LOCALAPPDATA%\Kiwi\desktop-settings.json` | 桌面开关（联网模型、本机执行） |
| `%LOCALAPPDATA%\Kiwi\logs` | `desktop.log`、`runtime.log`、`backend.log`、`qdrant.log` |
| `%LOCALAPPDATA%\Kiwi\WebView2` | WebView2 用户数据 |

设置页「桌面 → 数据位置」可复制数据目录与日志目录路径。应用不会把数据写入安装
目录，也不会写入系统级目录。

## 配置模型

桌面版没有默认模型。打开 **设置 → 模型**：

- **本机 Ollama / LM Studio**：例如 `http://127.0.0.1:11434/v1` 或
  `http://127.0.0.1:1234/v1`。loopback 地址不需要额外确认。
- **线上 OpenAI 兼容接口**：首次保存或测试非 loopback 地址时，界面会明确提示
  「笔记正文、选中文本和问题会发送到该地址」。拒绝则不会保存，也不会发起请求。
  确认后写入 `allow_online_models=true`。

LLM 与 embedding 是两套独立配置：

- 仅配置 LLM：Wiki 编译、学习出题可用；向量检索与需要 embedding 的问答不可用。
- 同时配置 embedding：语义检索、混合问答、Wiki 页面向量索引可用。
- embedding 可先用本机接口，也可改用线上接口。切换后到 **Wiki → 重建索引**
  重建页面向量；笔记向量会在保存编辑或重新导入时写入，也可调用
  `POST /api/notes/reindex?kb_id=<知识库 ID>&force=true` 主动重建。

未配置模型时不会自动下载任何模型，也不会重试外部接口。

## 离线边界

桌面版默认**不发起任何外网请求**：

- WebView2 只允许访问应用自身的 loopback origin；远程图片、favicon、YouTube、
  外部 iframe 显示本地占位，点击外链会被拦截并提示。
- 后端审计钩子拦截非 loopback 的 `connect` / DNS 解析；只有用户在设置中明确
  允许并登记的模型端点可以放行。
- 链接抓取、在线 OCR、飞书妙记 / 语音转写、语雀在线导入、远程 URL 导入、
  Web Push、学习联网核查在桌面版禁用；本地文件导入、本地 OCR 解析仍可用。
- 服务只监听 `127.0.0.1` 的随机端口，不开放局域网访问，也不添加防火墙规则。

**Evergreen 运行时边界**：默认构建使用系统 WebView2 Runtime，其更新由
Microsoft Edge Update 维护，属于系统组件流量，不是 Kiwi 的数据请求。需要完全
不依赖系统运行时与 Edge Update 的环境，使用带 Fixed Version 运行时的构建
（安装包体积增加约 250MB，运行时完全由应用目录加载）。

**审计钩子的边界**：它无法覆盖 C 扩展或子进程；桌面版同时用功能开关、WebView2
网络策略与便携 Python 的 `sitecustomize` 做多层限制。本机代码执行本身不是安全
沙箱（见下节）。

## 本机代码执行

默认为**关闭**。代码块与 Notebook 在关闭时点击运行会提示先在
**设置 → 桌面 → 本机代码执行** 中开启；开启前必须确认：

> 本机执行没有文件系统隔离，只运行可信代码。

开启后：

- 代码以当前 Windows 用户身份运行，可读取该用户可访问的文件；Job Object 只限制
  进程树、内存（单进程 2GB）与活动进程数，超时或关闭开关时终止整棵进程树。
- 使用随包的便携 Python，预装 `numpy`、`pandas`、`matplotlib`、`openpyxl`、
  `pillow`；**不允许运行期安装新包**，`%pip` / `%uv` / `!shell` / `%%bash` 不可用。
- 默认超时 60 秒，可在设置中调整为 5–600 秒。Notebook 超时会终止内核并重启，
  之前的变量状态会丢失。
- 代码子进程只继承最小环境变量，不包含 `KIWI_*`、数据库连接串、Fernet 密钥或
  控制令牌；`sitecustomize` 尽力阻止非 loopback 连接，但它不是安全边界。
- 关闭开关会立即终止全部 Windows 内核与正在运行的代码。

与 Docker 版的区别：Docker 使用 bubblewrap 做文件系统隔离；Windows 桌面版没有
等价的轻量隔离，因此默认关闭并明确标注「本机执行 · 非隔离」。

## 备份与恢复

自动备份默认开启，写入 `%LOCALAPPDATA%\Kiwi\backups\kiwi-<时间戳>\`：

- `db.dump`：PostgreSQL custom 格式；
- `uploads.tar.gz`：素材与附件；
- `fernet.key`：模型 API Key 的本地加密密钥（桌面版存在时）；
- `manifest.json`：版本、文件大小与 SHA-256。

备份包含数据库与解密密钥，按敏感数据保管。**不要**把备份上传到公共位置。

### 恢复

恢复会覆盖数据库，请先退出 Kiwi 并备份当前数据目录。以下命令使用随包的
PostgreSQL 16 工具；路径按实际安装位置调整。

```powershell
$AppDir  = "$env:LOCALAPPDATA\Programs\Kiwi"
$DataDir = "$env:LOCALAPPDATA\Kiwi"
$PgBin   = "$AppDir\runtime\_internal\pgserver\pginstall\bin"
$Backup  = "$DataDir\backups\kiwi-20261021-120000"

# 1. 启动应用自带的 PostgreSQL（集群在 $DataDir\pg，默认 trust 认证）
& "$PgBin\pg_ctl.exe" -D "$DataDir\pg" -o "-p 55432" `
  -l "$env:TEMP\kiwi-restore-pg.log" start

# 2. 恢复数据库（恢复到默认库 postgres）
& "$PgBin\pg_restore.exe" -h 127.0.0.1 -p 55432 -U postgres -d postgres `
  --clean --if-exists --no-owner --no-acl "$Backup\db.dump"

# 3. 停止临时 PostgreSQL
& "$PgBin\pg_ctl.exe" -D "$DataDir\pg" stop

# 4. 恢复附件与解密密钥
tar.exe -xzf "$Backup\uploads.tar.gz" -C "$DataDir\uploads"
Copy-Item "$Backup\fernet.key" "$DataDir\secrets\fernet.key" -Force
```

启动 Kiwi 后会执行必要的迁移。若没有恢复 `fernet.key`，已保存的模型 API Key
无法解密，需要在设置中重新填写。

## 故障排查

**启动停在某个阶段或提示失败**：打开 `%LOCALAPPDATA%\Kiwi\logs\runtime.log` 与
`desktop.log`，确认阶段（`postgres` / `qdrant` / `migrate` / `http`）与错误信息。

**PostgreSQL 因路径含中文或空格启动失败**：pgserver 的 `initdb` 对非 ASCII 路径
敏感。程序会尝试 8.3 短路径；若失败，可用 ASCII 路径启动：

```powershell
& "$env:LOCALAPPDATA\Programs\Kiwi\Kiwi.Desktop.exe" --data-dir "C:\KiwiData"
```

也可以在 NTFS 卷上启用 8.3 名称后重启应用。

**提示缺少 WebView2**：安装器会在系统缺少运行时时自动安装随包的 Evergreen
Standalone 安装程序；若被组策略拦截，可重新运行安装包，或从微软官网安装
WebView2 Runtime 后启动。也可以改用携带 Fixed Version 运行时的构建
（`-FixedWebView2`），完全不依赖系统运行时。

**端口冲突 / 启动缓慢**：服务使用随机 loopback 端口，通常不会冲突。首次启动
需要初始化 PostgreSQL 与内置演示库；杀毒软件实时扫描会明显拖慢。可将安装目录
加入排除项后重试。

**Qdrant 未启动**：未配置 embedding 时 Qdrant 失败不影响启动，只是向量能力
不可用；检查 `qdrant.log` 与 `%LOCALAPPDATA%\Kiwi\qdrant` 的写入权限。

**界面白屏 / 进程崩溃**：查看 `desktop.log` 中的 WebView2 错误；关闭后重新启动。
若仍失败，把 `logs` 目录与复现步骤一并保留。

**如何完全重置**：退出 Kiwi，将 `%LOCALAPPDATA%\Kiwi` 改名或移走（不要直接删除，
先保留备份），重新启动会生成全新数据目录。

## 从源码构建

构建必须在 Windows 10/11 x64 上进行；不支持 Wine 交叉打包。前置工具：

- Python 3.12（PyInstaller 不支持其他次版本）
- [uv](https://docs.astral.sh/uv/)
- Node.js 22
- .NET 10 SDK
- Inno Setup 6（仅生成安装包时需要）

缺工具时 `-Bootstrap` 会尝试用 `winget` 安装；也可以按脚本提示手动安装。

```powershell
# 完整构建：前端 + runtime + 宿主 + 安装包
powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Version 1.0.0

# 或双击 desktop\build.cmd
```

产物：

- `desktop\dist\Kiwi-Setup-1.0.0.exe`
- `desktop\dist\Kiwi-Setup-1.0.0.exe.sha256`
- `desktop\build\app\`：未打包的暂存目录，便于调试

### 参数

| 参数 | 说明 |
|---|---|
| `-Version` | 版本号，默认取 `frontend/package.json` |
| `-Clean` | 清理 `desktop\build` 与 `desktop\dist` |
| `-SkipFrontend` | 复用现有 `frontend\dist` |
| `-SkipRuntime` | 复用 / 跳过 PyInstaller 与便携 Python 准备 |
| `-SkipHost` | 跳过 .NET 宿主发布 |
| `-SkipInstaller` | 只生成暂存目录，不编译安装包 |
| `-SkipDownloads` | 只使用 `desktop\.cache` 缓存，缺失时失败，不联网 |
| `-SkipTests` | 跳过 `ruff` 与 `pytest`（Windows CI 使用） |
| `-NoWebView2Bundle` | 不随包携带 WebView2 Evergreen 安装器 |
| `-FixedWebView2` | 使用 `versions.json` 中配置的 Fixed Version 运行时 |
| `-Sign` | 使用 `SIGN_PFX_BASE64` / `SIGN_PFX_PASSWORD` 签名 |
| `-RequireSignature` | 与 `-Sign` 同时使用；构建结束校验签名，未签名则失败 |
| `-OutputDir` | 安装包输出目录 |
| `-Bootstrap` | 缺工具时尝试 `winget` 自动安装 |

第三方下载版本与 SHA-256 固定在 `desktop\versions.json`；升级组件时必须同时更新
URL、版本与校验值，并在 Windows 上重新冒烟。下载缓存在 `desktop\.cache`。

### 签名

```powershell
$env:SIGN_PFX_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("kiwi.pfx"))
$env:SIGN_PFX_PASSWORD = "..."
powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Sign -RequireSignature
```

签名使用 SHA-256 与 DigiCert 时间戳。证书与密码只通过环境变量传入，不写入仓库。

### CI

`.github/workflows/windows-release.yml` 在 `windows-latest` 上构建：

- 手动触发可指定版本；推送 `v*` 标签时自动使用标签版本；
- 构建后静默安装到临时目录，运行 `Kiwi.Desktop.exe --smoke-test`，再卸载并确认
  用户数据目录保留；
- 上传安装包、`.sha256` 与冒烟日志；标签构建自动创建 GitHub Release。

GitHub 运行器无法可靠驱动 WebView2 窗口，真实窗口、DPI、单实例与离线流量仍需在
Windows 虚拟机上按 `desktop\spike` 的检查项手工验收。

### 分发与许可

安装包内置 AGPL-3.0 授权的 PyMuPDF，因此 Kiwi 整体按 GNU Affero 通用公共许可证
第 3 版（AGPL-3.0）发布。`build.ps1` 会把仓库根目录的 `LICENSE` 与
`THIRD-PARTY-NOTICES.md` 复制到程序目录；对外分发安装包或修改版本时，还需保证
接收者可获取对应源代码（<https://github.com/LsWGG/Kiwi>）。若通过网络提供修改
版本，还需按 AGPL-3.0 第 13 条向用户提供对应源代码。

## 已知限制

- 只有 x64；Windows ARM64 未验证。
- 没有自动更新；升级需重新运行安装包。
- 没有托盘常驻 / 开机自启。
- 本机代码执行不是安全沙箱，不能运行不可信代码。
- 在线语雀、飞书、Web Push、链接抓取、在线 OCR 在桌面版被禁用。
- 系统用户名含非 ASCII 字符时，PostgreSQL 可能依赖 8.3 短路径或自定义 ASCII
  数据目录（见故障排查）。
- 安装包包含 AGPL-3.0 授权的 PyMuPDF，Kiwi 按 AGPL-3.0 发布；程序目录包含
  `LICENSE` 与 `THIRD-PARTY-NOTICES.md`。
