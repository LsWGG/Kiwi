# Kiwi Docker 部署指南

本文面向单机 / 内网自托管场景，使用 Docker Compose 启动前端、后端、PostgreSQL 与 Qdrant。默认端口全部避开开发环境与常见默认值。

## 架构与端口

```text
浏览器
  │  http://<host>:18473
  ▼
frontend (nginx)
  ├── /             → Vite 静态产物
  └── /api /media   → backend:8000
                        ├── postgres:5432
                        └── qdrant:6333 / 6334
```

| 服务 | 容器内端口 | 宿主机端口 | 监听范围 | 说明 |
|---|---|---|---|---|
| Web（nginx） | 80 | **18473** | 所有网卡 | 唯一需要对外开放的端口 |
| Backend（FastAPI） | 8000 | **18474** | 127.0.0.1 | API 文档 / 调试 |
| PostgreSQL | 5432 | **15432** | 127.0.0.1 | 数据库 |
| Qdrant HTTP | 6333 | **16333** | 127.0.0.1 | 向量检索 |
| Qdrant gRPC | 6334 | **16334** | 127.0.0.1 | 向量检索 |

除 Web 外的端口都只绑定本机回环地址；远程访问请通过 Web 端口的反向代理，或使用 SSH 隧道。

## 前置条件

- Docker Engine 24+，Docker Compose V2（`docker compose` 插件或独立的 `docker-compose` 命令均可）
- 启用 BuildKit（后端 Dockerfile 使用缓存挂载；建议安装 `docker-buildx-plugin`）
- 建议 4 核 / 8 GB 内存 / 10 GB 可用磁盘
- 构建前端需要 Node.js 20+ 与 npm（仅宿主机使用）
- 首次摄入文档时需要联网下载嵌入模型（约数百 MB）
- 若当前用户无 Docker 权限：将用户加入 `docker` 组，或以 `sudo` 运行部署脚本

## 快速开始

前端在宿主机构建后挂载进 nginx；Docker 只负责后端、数据库与向量库：

```bash
git clone https://github.com/LsWGG/Kiwi.git
cd Kiwi
(cd frontend && npm ci && npm run build)
./deploy.sh
```

`frontend/dist` 不存在时 `./deploy.sh` 也会自动在宿主机构建一次；也可以随时单独执行 `./deploy.sh frontend`。

首次执行会：

1. 从 `.env.prod.example` 生成 `.env.prod`（权限 600）；
2. 生成随机的 PostgreSQL 密码与 Fernet 密钥；
3. 构建后端镜像，并以 `nginx:1.27-alpine` 挂载 `frontend/dist` 启动四个容器；
4. 自动执行数据库迁移，并注入内置演示知识库。

访问：

- Web：`http://<服务器IP>:18473`
- API 文档：`http://127.0.0.1:18474/docs`（远程可用 `ssh -L 18474:127.0.0.1:18474 user@host`）
- 健康检查：`curl http://127.0.0.1:18474/api/health`

首次打开后，在「设置」中填写任意 OpenAI 兼容模型即可开始编译与问答。API Key 使用 `KIWI_FERNET_KEY` 加密后存入数据库。

### 手动准备环境

若不使用脚本自动生成：

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
# 编辑 KIWI_PUBLIC_ORIGIN、POSTGRES_PASSWORD、KIWI_FERNET_KEY
```

生成 Fernet 密钥：

```bash
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

`KIWI_PUBLIC_ORIGIN` 必须与浏览器实际访问地址一致（含端口），否则跨域相关能力可能异常；同源部署下 CORS 不参与主要流程，但仍建议填写正确。

### 国内网络加速

后端镜像默认使用国内镜像下载依赖，无需额外配置：

- **PyPI**：`https://pypi.tuna.tsinghua.edu.cn/simple`（`uv` 及其管理的全部 Python 包）
- **Debian**：`https://mirrors.tuna.tsinghua.edu.cn/debian` 与 `debian-security`（编译工具、bubblewrap、中文字体）
- **Hugging Face**：`https://hf-mirror.com`（首次摄入时下载嵌入模型）

构建阶段会缓存 apt 与 uv 下载，重复构建不会重新拉取依赖。前端在宿主机构建，建议为 npm 配置国内源：

```bash
npm config set registry https://registry.npmmirror.com
```

后端镜像源可在 `.env.prod` 中覆盖：

```dotenv
PYPI_INDEX_URL=https://pypi.org/simple
DEBIAN_MIRROR=http://deb.debian.org/debian
DEBIAN_SECURITY_MIRROR=http://security.debian.org/debian-security
NPM_REGISTRY=https://registry.npmjs.org
HF_ENDPOINT=https://huggingface.co
```

修改后重新执行 `./deploy.sh` 即可生效。基础镜像（Python / nginx / PostgreSQL / Qdrant）仍从 Docker Hub 拉取；若拉取缓慢，可为本机 Docker 配置 registry mirror，或提前 `docker pull` 对应镜像。

### 低内存主机构建（前端）

前端不再在 Docker 镜像内构建：Compose 使用 `nginx:1.27-alpine`，把宿主机的 `frontend/dist` 只读挂载到容器。这样低内存主机不会因 Vite 打包占用 2 GB 以上内存而在 `docker build` 阶段被 OOM 杀死（退出码 137）。

推荐流程：

```bash
# 在内存充足的机器或本机构建
(cd frontend && npm ci && npm run build)

# 把 frontend/dist 同步到服务器（或直接在服务器上构建）
rsync -av --delete frontend/dist/ user@server:/path/to/Kiwi/frontend/dist/

# 服务器上只启动 / 更新后端容器
./deploy.sh
```

前端更新后重新生成 `frontend/dist` 即可，nginx 直接读取新文件，无需重启或重建容器。若希望把静态产物打进不可变镜像，可先构建 `dist`，再执行 `docker build -f deploy/frontend.Dockerfile -t kiwi-frontend .`。

### 线上嵌入模型（无法本地向量化时）

默认使用本地 `fastembed` 模型，首次摄入时下载数百 MB 的 ONNX 模型。若部署环境内存不足、无法下载模型，或希望统一使用线上向量服务，推荐在应用内 **设置 → 向量模型** 切换到「线上接口」，填写地址、Key 与模型名并测试连接。应用内配置会加密保存到数据库，并优先于环境变量。

也可以在 `.env.prod` 中配置任意 OpenAI 兼容的 `/embeddings` 接口作为兜底（应用内未保存配置时生效）：

```dotenv
KIWI_EMBED_PROVIDER=openai
KIWI_EMBED_API_BASE=https://api.openai.com/v1
KIWI_EMBED_API_KEY=sk-...
KIWI_EMBED_API_MODEL=text-embedding-3-small
# 可选：请求超时、单批文本数与并发批次数
# KIWI_EMBED_API_TIMEOUT=60
# KIWI_EMBED_API_BATCH_SIZE=64
# KIWI_EMBED_API_CONCURRENCY=4
```

也兼容本地 Ollama 等实现，例如 `KIWI_EMBED_API_BASE=http://host.docker.internal:11434/v1`、`KIWI_EMBED_API_MODEL=nomic-embed-text`（无需 API Key）。

说明：

- 应用内保存配置后，`KIWI_EMBED_*` 仅在点击「恢复环境变量配置」后重新生效。
- 远程模式下所有知识库共享同一向量空间，知识库设置中的本地模型选项不再生效。
- 远程向量写入独立的 Qdrant collection，不会与本地模型的历史向量混用；切换模型或服务商会自动使用新 collection。
- 切换后已有素材的 raw 向量不会自动迁移，建议重新导入素材，并对 Wiki 执行一次「重建 Wiki」；否则旧内容只能依赖 Wiki 页面重新编译后的向量。
- 启用后，笔记、Wiki 与检索查询文本会发送到所配置的线上接口，请确认该服务的数据合规性。

### 端口调整

所有端口都在 `.env.prod` 中配置，修改后重新执行 `./deploy.sh`：

```dotenv
KIWI_HTTP_PORT=18473
KIWI_API_PORT=18474
POSTGRES_PORT=15432
QDRANT_HTTP_PORT=16333
QDRANT_GRPC_PORT=16334
```

若 18473 被占用，改成任意空闲端口（例如 `28473`），并同步修改 `KIWI_PUBLIC_ORIGIN`。

## 配置项

| 变量 | 默认值 | 说明 |
|---|---|---|
| `KIWI_PUBLIC_ORIGIN` | `http://localhost:18473` | 浏览器访问地址，用于 CORS |
| `KIWI_HTTP_PORT` | `18473` | Web 宿主机端口 |
| `KIWI_API_PORT` | `18474` | API 宿主机端口（仅本机） |
| `POSTGRES_PORT` | `15432` | PostgreSQL 宿主机端口 |
| `QDRANT_HTTP_PORT` | `16333` | Qdrant HTTP 宿主机端口 |
| `QDRANT_GRPC_PORT` | `16334` | Qdrant gRPC 宿主机端口 |
| `POSTGRES_USER` / `POSTGRES_DB` | `kiwi` / `kiwi` | 数据库账号与库名 |
| `POSTGRES_PASSWORD` | 自动生成 | 建议仅使用字母、数字、`-`、`_` |
| `KIWI_FERNET_KEY` | 自动生成 | 模型 Key 加密密钥，必须长期保持 |
| `PYPI_INDEX_URL` | 清华 PyPI 镜像 | 后端构建时的 Python 包源 |
| `DEBIAN_MIRROR` / `DEBIAN_SECURITY_MIRROR` | 清华 Debian 镜像 | 后端构建时的系统包源 |
| `NPM_REGISTRY` | `https://registry.npmmirror.com` | 宿主机前端构建建议使用的 npm 源（手动 `npm config set registry`） |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 本地嵌入模型下载地址，海外可设为官方地址 |
| `KIWI_EMBED_PROVIDER` | `local` | `local` 本地 fastembed；`openai` 使用线上接口 |
| `KIWI_EMBED_API_BASE` | 空 | 线上 embedding 接口地址，如 `https://api.openai.com/v1` |
| `KIWI_EMBED_API_KEY` | 空 | 线上接口 API Key（本地服务可留空） |
| `KIWI_EMBED_API_MODEL` | `text-embedding-3-small` | 线上 embedding 模型名 |
| `KIWI_RETRIEVAL_MIN_SCORE` | `0.4` | 检索最低余弦相似度；低于该值的命中不进入问答上下文与引用，设为 `0` 关闭过滤 |
| `KIWI_LLM_TIMEOUT` | `600` | LLM 请求超时（秒） |
| `TZ` | `Asia/Shanghai` | 容器时区 |

## 数据与持久化

| 卷 | 内容 |
|---|---|
| `kiwi-prod-pgdata` | PostgreSQL 全部业务数据 |
| `kiwi-prod-qdrantdata` | 向量集合 |
| `kiwi-prod-data` | 上传文件、附件、Notebook 工作区、Wiki Schema、嵌入模型缓存 |

容器重建不会删除以上数据卷。`docker compose ... down -v` **会**删除数据，请勿在需要保留数据时使用。

### 备份

```bash
# 数据库
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U kiwi -d kiwi | gzip > "kiwi-db-$(date +%F).sql.gz"

# 上传与 Notebook 数据
docker run --rm \
  -v kiwi-prod-data:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf "/backup/kiwi-data-$(date +%F).tar.gz" -C /data .
```

### 恢复

```bash
./deploy.sh down

gunzip -c kiwi-db-2026-10-18.sql.gz | \
  docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  psql -U kiwi -d kiwi

docker run --rm \
  -v kiwi-prod-data:/data \
  -v "$PWD":/backup \
  alpine tar xzf "/backup/kiwi-data-2026-10-18.tar.gz" -C /data

./deploy.sh
```

Qdrant 向量可以在恢复数据库后通过 Wiki 的「重建」/「重新索引」重新生成，不必单独备份。

## 日常运维

```bash
./deploy.sh ps                 # 状态
./deploy.sh logs backend       # 跟踪后端日志
./deploy.sh logs frontend
./deploy.sh restart            # 重启全部服务
./deploy.sh down               # 停止，保留数据卷
```

升级：

```bash
git pull

# 仅后端代码变化：重启 backend 即可，无需打包
./deploy.sh update

# 仅前端代码变化：重新生成 dist，nginx 直接读取新文件
./deploy.sh frontend

# 依赖（backend/pyproject.toml、uv.lock、Dockerfile）变化或首次部署
./deploy.sh
```

生产 Compose 把 `backend/app`、`backend/alembic` 与 `backend/alembic.ini` 以只读方式挂载进容器，镜像内的虚拟环境与系统依赖保持不变。`./deploy.sh update` 重启 backend 时会重新执行入口脚本，数据库迁移仍会自动应用，数据卷不受影响。只有依赖变化时才需要重新构建镜像。

## 排障

### Notebook 无法执行，提示「安全沙箱不可用」

Notebook 使用 bubblewrap 创建命名空间。Compose 已为 backend 添加：

```yaml
cap_add: [SYS_ADMIN]
security_opt: [seccomp=unconfined, apparmor=unconfined]
```

验证：

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec backend \
  bwrap --unshare-user --ro-bind /usr /usr -- true && echo sandbox-ok
```

若仍失败，检查宿主机是否允许用户命名空间：

```bash
sysctl kernel.unprivileged_userns_clone user.max_user_namespaces
```

部分发行版需要开启 `kernel.unprivileged_userns_clone=1`。沙箱内部依然会丢弃全部 capabilities、限制进程与内存，并只挂载当前笔记本的工作目录。

### 命令是 `docker-compose` 而不是 `docker compose`

`deploy.sh` 会优先使用 `docker compose` 插件；找不到时自动回退到独立的 `docker-compose` 命令。回退要求其为 **Compose V2**（`docker-compose version --short` 输出 `2.x`）：

```bash
docker-compose version --short   # 应输出 2.x
```

若输出 `1.x`，说明仍是已停止维护的 Compose V1，本项目的健康检查依赖与卷命名配置无法运行。请升级：

```bash
# Debian / Ubuntu（Compose V2 插件，安装后 docker compose 可用）
sudo apt-get install docker-compose-plugin

# 或安装独立的 V2 二进制（安装后 docker-compose 可用）
sudo apt-get install docker-compose-v2
```

### 构建报 `the --mount option requires BuildKit`

后端 Dockerfile 使用 `RUN --mount=type=cache` 复用 PyPI / apt 缓存，需要 BuildKit。`deploy.sh` 已自动导出 `DOCKER_BUILDKIT=1`，仍报错通常是因为直接调用了 Compose 或用了 `sudo` 清空环境变量：

```bash
# 手动构建时显式启用
DOCKER_BUILDKIT=1 docker compose --env-file .env.prod -f docker-compose.prod.yml build

# 使用 sudo 时保留该变量
sudo DOCKER_BUILDKIT=1 docker compose --env-file .env.prod -f docker-compose.prod.yml build
```

若提示找不到 buildx，请安装插件（Debian / Ubuntu）：

```bash
sudo apt-get install docker-buildx-plugin
```

或改用官方 Docker 软件源升级 Docker Engine 24+。不建议为了兼容旧版构建器删除缓存挂载，否则每次构建都会重新下载全部依赖。

### 部署后没有内置演示知识库

内置演示库会在后端启动时写入；若写入失败，API 仍会启动，知识库列表为空。先查看日志：

```bash
./deploy.sh logs backend | grep -i "内置\|builtin"
```

0.1.3 已修复演示数据中日期字段导致的首次建库回滚。升级后重启即可自动创建；也可以在知识库页点击「创建内置知识库」手动生成。该操作会按当前随包内容重建演示数据。

### 上传返回 413

nginx 默认允许 220 MB，后端单文件导入上限 200 MB。若需更大文件，同时调整 `deploy/nginx.conf` 的 `client_max_body_size` 与后端限制后重新构建前端镜像。

### 首次摄入很慢 / 模型下载失败

嵌入模型会下载到 `kiwi-prod-data` 卷的 `models/` 目录。查看日志：

```bash
./deploy.sh logs backend
```

默认已通过 `HF_ENDPOINT=https://hf-mirror.com` 使用国内镜像。若仍失败，可在 `.env.prod` 中换用其他镜像或官方地址后执行 `./deploy.sh restart`。

### 页面 502 / API 不通

```bash
./deploy.sh ps
./deploy.sh logs backend
```

确认 backend 健康检查通过；nginx 通过 Docker 内置 DNS 解析 `backend`，无需手工配置 IP。

### 流式回答卡住

nginx 已对 `/api/` 关闭 `proxy_buffering` 并把读超时放宽到 600 秒。若前面还有一层反向代理，需要同样关闭缓冲。

### 端口被占用

修改 `.env.prod` 中对应端口并重新 `./deploy.sh`。只有 Web 端口对外监听，冲突通常发生在 18473。

## 安全说明

- `.env.prod` 含数据库密码与 Fernet 密钥，权限应为 600，且已在 `.gitignore` 中忽略。
- 默认只有 Web 端口对所有网卡开放；PostgreSQL、Qdrant、API 均绑定 `127.0.0.1`。
- Kiwi 是单用户本地优先应用，没有内置登录体系。若要暴露到公网，请在前面加一层带认证与 TLS 的反向代理（如 Caddy Basic Auth、Authelia），不要直接开放 18473。
- `SYS_ADMIN` 仅用于 Notebook 沙箱创建命名空间；沙箱内部会 `--cap-drop ALL`。请把宿主机视为可信环境。
- Fernet 密钥丢失后，已保存的模型 API Key 无法解密，需要重新填写。

## 部署文件

```text
deploy.sh                    一键部署脚本
docker-compose.prod.yml      生产 Compose
.env.prod.example            环境变量模板
deploy/backend.Dockerfile    后端镜像
deploy/frontend.Dockerfile   可选：预构建 dist 的 nginx 运行时镜像
deploy/nginx.conf            静态托管与 API / 媒体代理
deploy/entrypoint.sh         迁移 + 启动
.dockerignore                构建上下文裁剪
```
