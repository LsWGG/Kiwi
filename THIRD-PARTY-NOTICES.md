# Kiwi 第三方组件声明

Copyright © 2026 LsWGG。Kiwi 按 GNU Affero 通用公共许可证第 3 版
（SPDX: AGPL-3.0-only）发布，完整文本见 [LICENSE](LICENSE)。Windows 桌面版
安装包包含下列第三方软件；各组件的著作权归其作者所有，按各自许可证使用。
本文件汇总许可信息，不构成法律意见。

## 随安装包分发的组件

| 组件 | 版本 | 许可证 | 说明 |
|---|---|---|---|
| PostgreSQL | 16（pgserver 随包） | PostgreSQL License | https://www.postgresql.org/about/licence/ |
| pgserver | 0.1.4 | MIT | 提供 PostgreSQL 二进制的 Python 封装 |
| Qdrant | 1.20.0 | Apache-2.0 | https://github.com/qdrant/qdrant |
| CPython（便携版） | 3.12.16 | PSF-2.0 | https://docs.python.org/3/license.html |
| NumPy | 2.5.4 | BSD-3-Clause | 便携 Python 运行包 |
| pandas | 3.0.6 | BSD-3-Clause | 便携 Python 运行包 |
| Matplotlib | 3.11.2 | PSF-based | 便携 Python 运行包 |
| openpyxl | 3.1.5 | MIT | 便携 Python 运行包 |
| Pillow | 12.3.0 | MIT-CMU | 便携 Python 运行包 |
| .NET Runtime | 10 | MIT | https://github.com/dotnet/runtime |
| Microsoft.Web.WebView2 SDK | 1.0.4314.35 | BSD-2-Clause 风格（NuGet 包内 LICENSE.txt） | https://aka.ms/webview |
| WebView2 Evergreen Runtime 安装程序 | 由 Microsoft 提供 | Microsoft Edge 使用条款 | 仅在系统缺少运行时时运行 |
| PyInstaller 引导器 | 6.16.0 | GPL-2.0-or-later（含 bootloader 例外） | 仅引导器随 runtime 分发 |
| Inno Setup 生成的安装器 | 6.x | Inno Setup License | 仅构建工具；安装器允许自由分发 |

## 后端 Python 依赖（随 runtime 打包）

| 组件 | 许可证 | 组件 | 许可证 |
|---|---|---|---|
| FastAPI | MIT | uvicorn | BSD-3-Clause |
| SQLAlchemy | MIT | asyncpg | Apache-2.0 |
| Alembic | MIT | Pydantic | MIT |
| qdrant-client | Apache-2.0 | openai-python | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause | python-multipart | Apache-2.0 |
| python-docx | MIT | markdown-it-py | MIT |
| aiofiles | Apache-2.0 | python-dotenv | BSD-3-Clause |
| httpx | BSD-3-Clause | trafilatura | Apache-2.0 |
| lxml | BSD-3-Clause | openpyxl | MIT |
| xlrd | BSD-3-Clause | pandas | BSD-3-Clause |
| Matplotlib | PSF-based | pywebpush | MPL-2.0 |
| PyMuPDF | **AGPL-3.0 或 Artifex 商业许可（双许可）** | | |

### PyMuPDF 与 AGPL-3.0

PyMuPDF 以 AGPL-3.0 与 Artifex 商业许可双许可方式提供。本项目选择遵循
AGPL-3.0：Kiwi 的整体分发（包括 Windows 安装包与 Docker 部署）按 GNU Affero
通用公共许可证第 3 版发布，完整文本见仓库根目录 [LICENSE](LICENSE)。

分发 Kiwi（包括安装包、镜像或修改版本）时，需同时满足：

- 随附 AGPL-3.0 许可证文本；Windows 安装包在程序目录中包含 `LICENSE`；
- 向接收者提供对应的完整源代码，包括构建脚本与锁定版本：
  <https://github.com/LsWGG/Kiwi>；
- 不对 AGPL-3.0 授予的权利附加额外限制。

若通过网络向用户提供修改版本，还需按 AGPL-3.0 第 13 条向这些用户提供对应源代码。

若希望以非 AGPL 条款分发，需向 Artifex 取得商业许可并移除 PyMuPDF。

- 源码：https://github.com/pymupdf/PyMuPDF
- AGPL-3.0 文本：https://www.gnu.org/licenses/agpl-3.0.txt
- 商业许可：https://artifex.com/licensing/

## 前端依赖（随 SPA 打包）

| 组件 | 许可证 | 组件 | 许可证 |
|---|---|---|---|
| Vue 3 / Vue Router / Pinia | MIT | Vite | MIT |
| Tailwind CSS | MIT | TipTap（ProseMirror） | MIT |
| AntV G6 | MIT | PDF.js（pdfjs-dist） | Apache-2.0 |
| CodeMirror | MIT | Mermaid | MIT |
| KaTeX | MIT | markdown-it | MIT |
| DOMPurify | MPL-2.0 OR Apache-2.0 | docx-preview | Apache-2.0 |
| SheetJS（xlsx） | Apache-2.0 | lowlight | MIT |

完整依赖树与许可证文本可从 `frontend/package-lock.json` 与
`backend/uv.lock` 复现；Docker 镜像包含的组件范围更大，仍以镜像内实际安装
的依赖为准。

## 获取源代码

- Kiwi 自身源代码（AGPL-3.0）：<https://github.com/LsWGG/Kiwi>
- 第三方源码地址见上表与各项目仓库；AGPL 组件（PyMuPDF）的完整对应源码可从
  上游仓库获取。
- 构建脚本与锁定版本：`desktop/build.ps1`、`desktop/kiwi-runtime.spec`、
  `desktop/installer/kiwi.iss`、`backend/uv.lock`、`frontend/package-lock.json`，
  第三方版本与校验值见 `desktop/versions.json`。
