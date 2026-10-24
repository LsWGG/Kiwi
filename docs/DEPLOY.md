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
./deploy.sh
```

首次执行会进入**渐进式交互向导**，只询问当前部署需要的项：

1. 浏览器访问地址（局域网默认填本机 IP，回车即可）；
2. 是否启用访问令牌（非 localhost 默认建议启用，可自动生成）；
3. 是否启用 Cloudflare Tunnel 公网只读分享（可选，见下文）；
4. 是否重新构建前端、是否在部署前备份（已有数据时）。

确认摘要后脚本会：

1. 从 `.env.prod.example` 生成 `.env.prod`（权限 600）；
2. 生成随机的 PostgreSQL 密码与 Fernet 密钥；
3. 在宿主机构建 `frontend/dist`（不存在或选择重建时）；
4. 构建后端镜像，并以 `nginx:1.27-alpine` 挂载 `frontend/dist` 启动容器；
5. 自动执行数据库迁移，并注入内置演示知识库。

无终端或自动化部署使用 `./deploy.sh --yes`，直接读取 `.env.prod` 现有配置；也可在任何时候单独执行 `./deploy.sh frontend` 重建前端。

访问：

- Web：`http://<服务器IP>:18473`
- API 文档：`http://127.0.0.1:18474/docs`（远程可用 `ssh -L 18474:127.0.0.1:18474 user@host`）
- 健康检查：`curl http://127.0.0.1:18474/api/health`

首次打开后，在「设置」中填写任意 OpenAI 兼容模型即可开始编译与问答。API Key 使用 `KIWI_FERNET_KEY` 加密后存入数据库。

### 手动准备环境

若不使用向导自动生成：

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
# 编辑 KIWI_PUBLIC_ORIGIN、POSTGRES_PASSWORD、KIWI_FERNET_KEY
# 可选：KIWI_ACCESS_TOKEN、KIWI_CLOUDFLARE_ENABLED、
#       CLOUDFLARE_TUNNEL_TOKEN、KIWI_PUBLIC_BASE_URL
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
# PostgreSQL 16 客户端（pg_dump）源；海外网络可改为官方地址
PGDG_MIRROR=https://mirrors.aliyun.com/postgresql/repos/apt
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

## 公网只读分享（Cloudflare Tunnel）

笔记的「只读分享链接」默认生成 `http://<内网地址>:18473/share/<token>`，只能在局域网打开。
如果已有托管在 Cloudflare 的域名，可以用 Named Tunnel 把**分享页和公开分享 API** 暴露到公网，
其余路径（笔记工作区、登录后的 API、媒体目录）继续只在内网可用。

部署脚本内置了 token 模式的 `cloudflared` 容器（Compose profile `cloudflare`），
NAS / Docker 部署无需在宿主机安装 systemd 服务，推荐使用方式 A。

### 方式 A：内置 cloudflared 容器（推荐）

先在 Cloudflare Zero Trust → **Networks → Tunnels** 创建 Named Tunnel，
复制 Tunnel Token（不要复制 credentials JSON），并为分享域名添加一条 CNAME
（`cloudflared tunnel route dns` 或 Zero Trust 面板自动创建）。

然后在 Kiwi 目录执行：

```bash
./deploy.sh cloudflare
```

向导会询问：

1. Tunnel Token（输入时不回显）；
2. 公网分享域名（如 `https://share.example.com`，只填协议 + 域名）。

脚本会写入 `.env.prod`、启动 `kiwi-prod-cloudflared`，并重建 backend 让新分享域名生效。
之后在 Zero Trust → 你的 Tunnel → **Public Hostname** 添加四条规则，Service 均填
`http://frontend:80`（cloudflared 与 nginx 在同一 Compose 网络）：

| Hostname | Path | Service |
|---|---|---|
| `share.example.com` | `/share/` | `http://frontend:80` |
| `share.example.com` | `/api/share/` | `http://frontend:80` |
| `share.example.com` | `/assets/` | `http://frontend:80` |
| `share.example.com` | `/favicon` | `http://frontend:80` |

其余路径由 Cloudflare 返回 404。也可以只把整站指向 `http://frontend:80`，但这样公网能访问
工作区登录页；即使启用了 `KIWI_ACCESS_TOKEN`，也建议保留路径白名单。

非交互环境可直接传入配置（Token 与域名会写入 `.env.prod`）：

```bash
CLOUDFLARE_TUNNEL_TOKEN='<token>' \
KIWI_PUBLIC_BASE_URL='https://share.example.com' \
./deploy.sh cloudflare
```

常用命令：

```bash
./deploy.sh cloudflare status   # 查看开关、域名与容器状态
./deploy.sh cloudflare off      # 停止隧道（保留 Token 与域名）
./deploy.sh logs cloudflared    # 查看隧道日志
```

也可以在 `./deploy.sh` 向导的「Cloudflare Tunnel 公网分享」一步选择启用；选择「否」
并确认停止后，`cloudflared` 容器会被停止，公网链接立即不可访问。

### 方式 B：宿主机安装 cloudflared（不使用 Docker 运行隧道）

若宿主机已安装 `cloudflared` 并希望由 systemd 管理：

```bash
# 安装：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel login
cloudflared tunnel create kiwi-share     # 记下 Tunnel ID
cloudflared tunnel route dns kiwi-share share.example.com
```

复制示例配置并按注释替换 Tunnel ID 与域名：

```bash
sudo mkdir -p /etc/cloudflared
sudo cp deploy/cloudflared.example.yml /etc/cloudflared/config.yml
sudo vi /etc/cloudflared/config.yml
```

核心是 ingress 的路径白名单（宿主机模式回源到 `127.0.0.1:18473`）：

```yaml
ingress:
  - hostname: share.example.com
    path: ^/(share/|api/share/|assets/|favicon)
    service: http://127.0.0.1:18473
  - hostname: share.example.com
    service: http_status:404
  - service: http_status:404
```

- `/share/<token>`：分享页 SPA；
- `/api/share/`：公开分享内容与签名媒体（图片、附件）；
- `/assets/`、`/favicon`：前端静态资源。

其余请求直接 404，公网看不到工作区页面，也拿不到 `/api/notes` 等登录态接口。

安装为系统服务并启动：

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

同样需要在 `.env.prod` 中填写 `KIWI_PUBLIC_BASE_URL`（方式 A 的向导会自动写入），
然后执行 `./deploy.sh update` 让 backend 重新读取环境变量。

### 分享域名与安全说明

`KIWI_PUBLIC_BASE_URL` 决定创建分享链接时使用的公网地址；不配置时退回当前浏览器访问地址
（内网创建就是内网链接）。方式 A 的向导会自动设置；手动修改后执行 `./deploy.sh update` 即可生效。

- 分享页与公开 API 同源，无需修改 `KIWI_PUBLIC_ORIGIN`（CORS 只影响工作区）。
- 已启用 `KIWI_ACCESS_TOKEN` 时，`/api/share/` 仍在公开白名单内，访客无需登录；
  但如果页面经过 Cloudflare Access 保护，需要为该主机名的 `/share/` 与 `/api/share/`
  配置 Bypass 策略，否则匿名访客会先被 Access 登录页拦下。
- 分享内容本身仍受有效期、访问密码、撤销控制；上锁笔记不能创建分享。
- 媒体链接带短时签名，过期后刷新分享页即可重新获取；请勿把单个图片地址另行外传。
- 公网 Hostname 只放行上述四个路径后，`/`、`/api/notes`、`/api/health` 等均应返回 404；
  验证：`curl -I https://share.example.com/`。
- **国内访问**：Cloudflare 免费版的中国大陆流量通常回源到香港/新加坡/日本等节点，
  延迟和稳定性不及境内直连。若分享对象主要在国内，可改用 Tailscale Funnel
  或境内服务器的 frp / nginx 反代，配置方式相同（只需放行上述四个路径并设置
  `KIWI_PUBLIC_BASE_URL`）。

> 只需要分享页上网、不需要固定域名时，也可以临时用 Quick Tunnel
> （`cloudflared tunnel --url http://127.0.0.1:18473`），但每次重启地址都会变，不适合长期分享。

## 语音转写（可选）

笔记工作区「新建 → 语音转写」使用本地 faster-whisper，无需外部 API：

- 首次转写会把模型下载到 `KIWI_WHISPER_MODEL_DIR`（默认 `data/models/whisper`），
  `small` 约 500MB。Docker 部署请把该目录挂载为持久卷，避免重建容器后重复下载。
- 纯 CPU 即可运行；有 GPU 时可设 `KIWI_WHISPER_DEVICE=cuda`、
  `KIWI_WHISPER_COMPUTE_TYPE=float16`。
- 音频先保存为临时文件，转写完成后立即删除；任务走持久化队列，需要启用 worker。
- `KIWI_WHISPER_LANGUAGE=auto` 自动识别语言，也可固定为 `zh` / `en` 等。

## Web Push 提醒（可选）

学习模式「提醒设置」可开启到期复习 / 待办提醒与每周学习报告推送：

- 浏览器推送要求页面通过 **HTTPS** 访问（`localhost` 除外）；用 Cloudflare Tunnel、
  Tailscale Funnel 或 nginx 反代暴露主站后即可订阅。
- VAPID 密钥在首次访问提醒设置时自动生成，私钥以 `KIWI_FERNET_KEY` 加密存入数据库。
  更换 `KIWI_FERNET_KEY` 后旧私钥无法解密，需要清空 `system_settings` 中的
  `push_vapid_*` 字段并重新订阅。
- 提醒由后端调度器每 60 秒检查一次，需要 `KIWI_BACKGROUND_JOBS=true`。
- `KIWI_PUSH_CONTACT` 填写 `mailto:` 地址，作为 VAPID 联系信息。

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
| `KIWI_ACCESS_TOKEN` | 空 | 可选访问令牌；设置后 `/api`、`/media`、`/metrics` 需要登录 |
| `KIWI_ACCESS_COOKIE_NAME` | `kiwi_access` | 登录 Cookie 名称 |
| `KIWI_PUBLIC_BASE_URL` | 空 | 公网分享域名（如 `https://share.example.com`）；留空时分享链接使用当前访问地址 |
| `KIWI_CLOUDFLARE_ENABLED` | `false` | 是否启用内置 `cloudflared` 容器（Compose profile `cloudflare`） |
| `CLOUDFLARE_TUNNEL_TOKEN` | 空 | Cloudflare Named Tunnel 的 Token；启用隧道时必填 |
| `KIWI_PUSH_CONTACT` | `mailto:admin@example.com` | Web Push 联系地址，需以 `mailto:` 或 `https:` 开头 |
| `KIWI_WHISPER_ENABLED` | `true` | 是否启用本地语音转写 |
| `KIWI_WHISPER_MODEL` | `small` | faster-whisper 模型（tiny / base / small / medium / large-v3） |
| `KIWI_WHISPER_DEVICE` | `cpu` | 转写设备（`cpu` / `cuda`） |
| `KIWI_WHISPER_COMPUTE_TYPE` | `int8` | 计算精度；CPU 建议 `int8`，GPU 可用 `float16` |
| `KIWI_WHISPER_LANGUAGE` | `auto` | 默认识别语言，`auto` 为自动检测 |
| `KIWI_WHISPER_MODEL_DIR` | `data/models/whisper` | 模型下载目录，Docker 部署需持久化 |
| `KIWI_RATE_LIMIT_ENABLED` | `true` | 是否启用 LLM / 导入 / 代码执行接口限流 |
| `KIWI_RATE_LIMIT_LLM_PER_MINUTE` | `20` | 每 IP 每分钟 LLM 请求上限 |
| `KIWI_RATE_LIMIT_IMPORT_PER_MINUTE` | `10` | 每 IP 每分钟导入请求上限 |
| `KIWI_RATE_LIMIT_CODE_PER_MINUTE` | `30` | 每 IP 每分钟代码执行请求上限 |
| `KIWI_BACKGROUND_JOBS` | `true` | 是否启动演示库种子、笔记索引巡检、定时编译与自动备份；本地实例直连共享库时建议设为 `false` |
| `KIWI_JOB_WORKER_ENABLED` | `true` | 是否消费持久化任务队列（导入 / 编译）；独立于 `KIWI_BACKGROUND_JOBS`，设为 `false` 时任务只会排队 |
| `KIWI_BACKUP_ENABLED` | `true` | 是否启用自动备份 |
| `KIWI_BACKUP_INTERVAL_HOURS` | `24` | 自动备份间隔（小时） |
| `KIWI_BACKUP_RETENTION_DAYS` | `14` | 备份保留天数 |
| `KIWI_OPS_RETENTION_DAYS` | `14` | 后台任务与审计日志保留天数；`0` 关闭自动清理 |
| `PGDG_MIRROR` | 阿里云 PGDG 镜像 | 后端镜像安装 `postgresql-client-16` 的 apt 源 |
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

后端默认每 24 小时自动执行一次备份（`KIWI_BACKUP_ENABLED` / `KIWI_BACKUP_INTERVAL_HOURS`），
写入数据卷的 `/app/data/backups`。也可以在 **设置 → 运维 → 自动备份** 点击「立即备份」。

后端镜像安装的是 PostgreSQL 16 客户端（`pg_dump`），必须与服务端大版本一致。
升级后需要重新构建镜像（`./deploy.sh build && ./deploy.sh update`，或直接执行完整的
`./deploy.sh`）；仅执行 `./deploy.sh update` 不会更新镜像内的系统包。若数据库服务端
更换了大版本，需同步调整 Compose 的 PostgreSQL 镜像与 Dockerfile 中的客户端版本。

宿主机脚本适合纳入 crontab，或在升级 / 迁移前手动留档：

```bash
# Docker 生产栈：导出数据库 + uploads，并写入 manifest.json（含 sha256）
./scripts/backup.sh

# 宿主机直连数据库（本地开发 / 无 Docker 环境）
./scripts/backup.sh --local

# 自定义保留天数与输出目录
BACKUP_RETENTION_DAYS=30 BACKUP_DIR=/data/kiwi-backups ./scripts/backup.sh
```

输出结构与应用内备份一致，`manifest.json` 记录版本、提交、数据库与文件校验和：

```text
backups/kiwi-20261021-120000/
  db.dump          # PostgreSQL custom format
  uploads.tar.gz   # 上传附件（根目录为 uploads 内容）
  manifest.json
```

建议把备份目录同步到另一块磁盘或对象存储；Qdrant 向量可通过 Wiki 的「重建」/「重新索引」重新生成，不必单独备份。

### 恢复

> 恢复会覆盖目标数据库中的同名对象，属于不可逆操作。脚本要求 `--yes`，
> Docker 模式会先停止 backend；本地模式请先自行停止后端进程。

```bash
# Docker 生产栈：数据库 + 附件，恢复后自动启动 backend
./scripts/restore_backup.sh backups/kiwi-20261021-120000 --with-uploads --yes

# 仅数据库
./scripts/restore_backup.sh backups/kiwi-20261021-120000 --yes

# 宿主机直连：恢复到另一个库（演练推荐）
TARGET_DB=kiwi_restoretest KIWI_DATABASE_URL=postgresql://... \
  ./scripts/restore_backup.sh backups/kiwi-20261021-120000 --local --yes
```

脚本会先校验 `manifest.json` 中的 sha256，再调用 `pg_restore --clean --if-exists`。
恢复完成后请到 Wiki 执行一次「重建 Wiki」，使 Qdrant 向量与回滚后的数据一致。

**恢复演练（2026-10-21）**：在独立测试库 `kiwi_locktest` 上执行
`backup.sh --local` → 新建空库 `kiwi_restoretest` → `restore_backup.sh --local --with-uploads`。
恢复后 37 张表、知识库 / 笔记 / 任务 / 审计行数与 alembic 版本（`b7c1d2e3f4a5`）均与源库一致，
示例附件字节内容一致。演练使用 PostgreSQL 16 客户端，避免 18 客户端向 16 服务端写入
`transaction_timeout` 参数导致告警。

## 日常运维

```bash
./deploy.sh ps                 # 状态
./deploy.sh logs backend       # 跟踪后端日志
./deploy.sh logs frontend
./deploy.sh restart            # 重启全部服务
./deploy.sh down               # 停止，保留数据卷
./deploy.sh cloudflare status  # 公网隧道状态（启用后）
./deploy.sh cloudflare off     # 停止公网隧道
```

升级：

```bash
git pull

# 仅后端代码变化：按最新源码与环境变量重建 backend，无需打包
./deploy.sh update

# 仅前端代码变化：重新生成 dist，nginx 直接读取新文件
./deploy.sh frontend

# 依赖（backend/pyproject.toml、uv.lock、Dockerfile）变化或首次部署
./deploy.sh
```

自动化或没有交互终端时使用 `./deploy.sh --yes`；它会直接采用 `.env.prod` 中的配置，
不会询问、不会自动备份，也不会重新构建已存在的 `frontend/dist`。

生产 Compose 把 `backend/app`、`backend/alembic` 与 `backend/alembic.ini` 以只读方式挂载进容器，镜像内的虚拟环境与系统依赖保持不变。`./deploy.sh update` 会重建 backend 容器（而不是仅重启），因此 `.env.prod` 中的环境变量变更也会生效，同时重新执行入口脚本、自动应用数据库迁移，数据卷不受影响。只有依赖变化时才需要重新构建镜像。

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

`./deploy.sh` 在交互模式下会自动检测 18473 是否被其他程序占用，并询问新的 Web 端口；
非交互部署可修改 `.env.prod` 中 `KIWI_HTTP_PORT` 后重新执行 `./deploy.sh --yes`。
只有 Web 端口对外监听，冲突通常发生在 18473。

## 安全说明

- `.env.prod` 含数据库密码与 Fernet 密钥，权限应为 600，且已在 `.gitignore` 中忽略。
- 默认只有 Web 端口对所有网卡开放；PostgreSQL、Qdrant、API 均绑定 `127.0.0.1`。
- 单用户本地应用默认不启用登录。若要在家庭 / 办公内网访问，建议设置访问令牌：

  ```dotenv
  KIWI_ACCESS_TOKEN=change_me_to_a_long_random_token
  ```

  重启后浏览器首次访问会进入登录页，登录态通过 HttpOnly Cookie 保存 30 天。
  `/api/health`、`/api/auth/*` 与前端静态资源保持公开，供健康检查与登录页使用；
  `/api`、`/media` 与 `/metrics` 需要令牌（支持 `X-Access-Token`、Bearer 或登录 Cookie）。
  如使用 Prometheus 抓取，请在抓取配置中携带该请求头。

- 若要直接暴露到公网，仍建议在前面加一层带 TLS 与认证的反向代理（如 Caddy / Authelia），
  访问令牌只是应用层的最低门槛，不替代 HTTPS。
- `SYS_ADMIN` 仅用于 Notebook 沙箱创建命名空间；沙箱内部会 `--cap-drop ALL`。请把宿主机视为可信环境。
- Fernet 密钥丢失后，已保存的模型 API Key 无法解密，需要重新填写；上锁笔记的加密正文同样依赖它。

## 部署文件

```text
deploy.sh                    一键部署脚本
docker-compose.prod.yml      生产 Compose
.env.prod.example            环境变量模板
deploy/backend.Dockerfile    后端镜像
deploy/frontend.Dockerfile   可选：预构建 dist 的 nginx 运行时镜像
deploy/nginx.conf            静态托管与 API / 媒体代理
deploy/entrypoint.sh         迁移 + 启动
scripts/backup.sh            宿主机备份（数据库 + uploads + manifest）
scripts/restore_backup.sh    宿主机恢复（校验 + pg_restore）
.dockerignore                构建上下文裁剪
```
