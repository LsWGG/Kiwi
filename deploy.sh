#!/usr/bin/env bash
# ==============================================================================
# Kiwi Docker 生产部署脚本
#   ./deploy.sh            构建后端镜像并启动（前端使用已构建的 frontend/dist）
#   ./deploy.sh frontend   在宿主机构建前端（npm ci + npm run build）
#   ./deploy.sh ps         查看状态
#   ./deploy.sh logs [svc] 跟踪日志
#   ./deploy.sh restart    重启
#   ./deploy.sh down       停止（保留数据卷）
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

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
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
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
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
}

command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker Engine"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose 插件"

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
