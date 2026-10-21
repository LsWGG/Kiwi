#!/usr/bin/env bash
# ==============================================================================
# Kiwi Docker 生产部署脚本
#   ./deploy.sh            构建后端镜像并启动（前端使用已构建的 frontend/dist）
#   ./deploy.sh update     更新后端代码后重启 backend（源码已挂载，无需重建镜像）
#   ./deploy.sh frontend   在宿主机构建前端（npm ci + npm run build）
#   ./deploy.sh ps         查看状态
#   ./deploy.sh logs [svc] 跟踪日志
#   ./deploy.sh restart    重启全部服务
#   ./deploy.sh down       停止（保留数据卷）
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# 构建版本同时写入前端 build-info.json 与后端镜像环境变量，供设置页做一致性检查。
KIWI_BUILD_COMMIT="${KIWI_BUILD_COMMIT:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
KIWI_BUILD_TIME="${KIWI_BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
export KIWI_BUILD_COMMIT KIWI_BUILD_TIME
echo "[kiwi-deploy] 构建版本：${KIWI_BUILD_COMMIT} @ ${KIWI_BUILD_TIME}"

ENV_FILE=".env.prod"
COMPOSE_FILE="docker-compose.prod.yml"

# 后端 Dockerfile 使用 RUN --mount=type=cache 复用依赖缓存，必须启用 BuildKit。
# 显式导出可覆盖宿主机 / daemon 中 DOCKER_BUILDKIT=0 的配置。
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

die() { echo "[kiwi-deploy] $*" >&2; exit 1; }

gen_password() {
  openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | cut -c1-24
}

gen_fernet_key() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr '+/' '-_'
  else
    die "需要 python3 或 openssl 来生成 Fernet 密钥"
  fi
}

ensure_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp .env.prod.example "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "[kiwi-deploy] 已创建 $ENV_FILE"
  fi

  if grep -q '^POSTGRES_PASSWORD=change_me' "$ENV_FILE"; then
    local pass
    pass="$(gen_password)"
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pass}|" "$ENV_FILE"
    echo "[kiwi-deploy] 已生成 PostgreSQL 密码"
  fi

  if grep -q '^KIWI_FERNET_KEY=change_me' "$ENV_FILE"; then
    local key
    key="$(gen_fernet_key)"
    sed -i "s|^KIWI_FERNET_KEY=.*|KIWI_FERNET_KEY=${key}|" "$ENV_FILE"
    echo "[kiwi-deploy] 已生成 Fernet 密钥"
  fi
}

compose() {
  "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

ensure_buildkit() {
  # Compose v2 优先调用 buildx；没有插件时由 daemon 内建 BuildKit 兜底。
  if ! docker buildx version >/dev/null 2>&1; then
    echo "[kiwi-deploy] 提示：未检测到 docker buildx 插件。若构建报 '--mount option requires BuildKit'，" >&2
    echo "              请安装 docker-buildx-plugin（或升级 Docker Engine）后重试。" >&2
  fi
}

build_frontend() {
  command -v npm >/dev/null 2>&1 || die "未找到 npm，请先安装 Node.js 20+ 后在 frontend/ 中构建"
  echo "[kiwi-deploy] 在宿主机构建前端（frontend/dist）…"
  (
    cd frontend
    if [ ! -d node_modules ]; then
      npm ci --no-audit --no-fund
    fi
    npm run build
  )
  [ -f frontend/dist/index.html ] || die "前端构建失败：frontend/dist/index.html 不存在"
}

ensure_frontend_dist() {
  if [ -f frontend/dist/index.html ]; then
    return
  fi
  echo "[kiwi-deploy] 未找到 frontend/dist，先构建前端…"
  build_frontend
}

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
}

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker Engine"

# Compose 命令探测：优先 `docker compose` 插件，其次独立的 `docker-compose`。
# 独立命令必须为 V2（Compose V1 已停止维护，不支持本项目的 healthcheck 依赖、
# 卷命名等配置）。
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_VERSION="$(docker-compose version --short 2>/dev/null || true)"
  if [ -z "$COMPOSE_VERSION" ]; then
    COMPOSE_VERSION="$(docker-compose version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  fi
  # 只比较主版本：独立发行版存在 2.x / 3.x / 5.x 等版本号，
  # 只要 >= 2 都是兼容 Compose V2 规范的实现。
  COMPOSE_MAJOR="${COMPOSE_VERSION%%.*}"
  case "$COMPOSE_MAJOR" in
    ''|*[!0-9]*)
      die "无法识别 Docker Compose 版本（${COMPOSE_VERSION:-未知}），本项目需要 Compose V2。"
      ;;
  esac
  if [ "$COMPOSE_MAJOR" -lt 2 ]; then
    die "检测到 Docker Compose ${COMPOSE_VERSION:-V1}，本项目需要 Compose V2。请安装 docker-compose-plugin（或 docker-compose-v2）后重试。"
  fi
  COMPOSE_CMD=(docker-compose)
else
  die "未找到 Docker Compose V2。请安装 docker-compose-plugin 或独立的 docker-compose（V2）后重试。"
fi

CMD="${1:-up}"
case "$CMD" in
  up|start)
    ensure_env
    ensure_frontend_dist
    ensure_buildkit
    compose up -d --build
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    echo
    echo "[kiwi-deploy] Kiwi 已启动"
    echo "  Web   http://localhost:${KIWI_HTTP_PORT:-18473}"
    echo "  API   http://localhost:${KIWI_API_PORT:-18474}/docs"
    echo "  数据卷 kiwi-prod-pgdata / kiwi-prod-qdrantdata / kiwi-prod-data"
    ;;
  down|stop)
    ensure_env
    compose down
    echo "[kiwi-deploy] 已停止（数据卷保留）"
    ;;
  update|reload)
    ensure_env
    # 后端 app / alembic 以 bind mount 运行，重启进程即可加载新代码。
    # 依赖（pyproject.toml / uv.lock）变化时仍需 ./deploy.sh up 重新构建。
    compose restart backend
    echo "[kiwi-deploy] 后端已重启，挂载的源码已生效"
    ;;
  restart)
    ensure_env
    compose restart
    ;;
  ps|status)
    ensure_env
    compose ps
    ;;
  logs)
    shift || true
    ensure_env
    compose logs -f --tail=200 "$@"
    ;;
  frontend)
    build_frontend
    ;;
  build)
    ensure_env
    build_frontend
    ensure_buildkit
    compose build
    ;;
  *)
    usage
    exit 1
    ;;
esac
