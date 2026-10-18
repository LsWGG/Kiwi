#!/usr/bin/env bash
# ==============================================================================
# Kiwi 一键启动脚本（开发模式）
# 幂等：可重复执行。检测环境 → 首次生成 .env → 拉起基础设施 → 迁移 → 启动前后端
#
# sudo 密码策略：若当前用户无 docker 权限，脚本通过 SUDO_PASS 环境变量
# 或交互式 read -s 获取，经 stdin 管道传给 `sudo -S`，绝不写入任何文件。
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${CYAN}[kiwi]${NC} $*"; }
ok()    { echo -e "${GREEN}[kiwi]${NC} $*"; }
warn()  { echo -e "${YELLOW}[kiwi-warn]${NC} $*"; }
die()   { echo -e "${RED}[kiwi-error]${NC} $*" >&2; exit 1; }

# ---------- 0. 预检 ----------
command -v docker >/dev/null || die "未找到 docker，请先安装 Docker"
command -v uv >/dev/null    || die "未找到 uv，请先安装（https://docs.astral.sh/uv/）"
command -v node >/dev/null  || die "未找到 node，请先安装 Node.js ≥ 20"
command -v npm >/dev/null   || die "未找到 npm"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose 插件"

# ---------- 1. 生成 .env（仅首次） ----------
if [ ! -f .env ]; then
  info "首次运行：生成 .env 与随机密钥…"
  if [ ! -f .env.example ]; then die ".env.example 缺失"; fi
  cp .env.example .env
  FERNET_KEY="$(uv run --with cryptography python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null \
    || python3 -c 'import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
  PG_PASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
  SECRET="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASS}|" .env
  sed -i "s|^KIWI_DATABASE_URL=.*|KIWI_DATABASE_URL=postgresql+asyncpg://kiwi:${PG_PASS}@localhost:5432/kiwi|" .env
  sed -i "s|^KIWI_FERNET_KEY=.*|KIWI_FERNET_KEY=${FERNET_KEY}|" .env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
  ok ".env 已生成（含随机密钥）。"
else
  ok ".env 已存在，跳过生成。"
fi
set -a; source .env; set +a

# ---------- 2. Docker 权限检测与基础设施 ----------
docker_cmd() { docker "$@"; }
if ! docker info >/dev/null 2>&1; then
  warn "当前用户无 docker 权限，使用 sudo 执行 docker compose…"
  SUDO_PASS="${SUDO_PASS:-}"
  if [ -z "$SUDO_PASS" ]; then
    read -r -s -p "[kiwi] sudo 密码: " SUDO_PASS; echo
  fi
  docker_cmd() {
    echo "$SUDO_PASS" | sudo -S docker "$@" 2>/dev/null
  }
  docker_cmd info >/dev/null 2>&1 || die "sudo docker 仍失败：密码错误或用户不在 sudo 组。"
fi

info "基础设施健康探测（外部已起则跳过 compose）…"
INFRA_READY=0
# Qdrant /healthz
if curl -sf http://localhost:${QDRANT_PORT:-6333}/healthz >/dev/null 2>&1; then
  # PG 探活
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h ${POSTGRES_HOST:-localhost} -p ${POSTGRES_PORT:-5432} -U ${POSTGRES_USER:-kiwi} >/dev/null 2>&1 && INFRA_READY=1 || true
  else
    INFRA_READY=1  # 无 pg_isready 时以 Qdrant 探活为代理
  fi
fi
if [ "$INFRA_READY" = "1" ]; then
  ok "检测到外部基础设施已就绪（Qdrant/PG 可达），跳过 docker compose。"
else
  info "拉起基础设施容器（postgres / qdrant / redis）…"
  docker_cmd compose up -d 2>&1 | sed 's/^/[compose] /'

  info "等待容器健康…"
  timeout 150 bash -c '
    set -euo pipefail
    for i in $(seq 1 60); do
      status="$(docker_cmd() { echo "$SUDO_PASS" | sudo -S docker "$@" 2>/dev/null; }; docker_cmd compose ps --format json 2>/dev/null || true)"
      unhealthy="$(echo "$status" | grep -cE "unhealthy|exited" || true)"
      healthy="$(echo "$status" | grep -c "\"Health\":\"healthy\"" || true)"
      [ "$unhealthy" -ge 1 ] && { echo "ERROR unhealthy container"; exit 2; }
      [ "$healthy" -ge 3 ] && { echo "HEALTHY"; exit 0; }
      [ $((i % 5)) -eq 0 ] && echo "…等待中 ($((i * 5))s)"
      sleep 5
    done
    echo "TIMEOUT"
    exit 1
  ' || die "基础设施健康检查超时，请查看 docker compose logs。"

  ok "基础设施就绪。"
fi

# ---------- 3. 后端依赖与迁移 ----------
info "同步后端依赖（uv, Python 3.12）…"
( cd backend && uv sync )
info "执行数据库迁移…"
( cd backend && uv run alembic upgrade head )

# ---------- 4. 前端依赖 ----------
info "安装前端依赖（npm）…"
if ! command -v npm >/dev/null; then warn "npm 不可用，跳过前端安装"; fi

# ---------- 5. 并行启动前后端 ----------
# 端口可配/自动退避：被其他服务占用时自动 +1 找空端口。
# 可显式指定 BACKEND_PORT=8001 FRONTEND_PORT=5174 bash run.sh 启动。
BACKEND_BASE="${BACKEND_PORT:-8000}"
FRONTEND_BASE="${FRONTEND_PORT:-5173}"
port_free() { ! (ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "(:|\.)$1\s*\$"); }
BACKEND_PORT="$BACKEND_BASE"
while [ "$BACKEND_PORT" -lt $((BACKEND_BASE + 20)) ] && ! port_free "$BACKEND_PORT"; do
  BACKEND_PORT=$((BACKEND_PORT + 1)); info "后端端口 $((BACKEND_PORT - 1)) 被占用，改用 $BACKEND_PORT"
done
FRONTEND_PORT="$FRONTEND_BASE"
while [ "$FRONTEND_PORT" -lt $((FRONTEND_BASE + 20)) ] && ! port_free "$FRONTEND_PORT"; do
  FRONTEND_PORT=$((FRONTEND_PORT + 1)); info "前端端口 $((FRONTEND_PORT - 1)) 被占用，改用 $FRONTEND_PORT"
done
info "启动后端 (http://localhost:${BACKEND_PORT}) 与前端 (http://localhost:${FRONTEND_PORT})…"
BACKEND_PID=""; FRONTEND_PID=""
cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  echo; ok "已停止 Kiwi 服务。"
}
trap cleanup EXIT INT TERM

( cd backend && exec uv run uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" ) &
BACKEND_PID=$!

if command -v npm >/dev/null && [ -d frontend ]; then
  (
    cd frontend
    VITE_BACKEND_PROXY="http://localhost:${BACKEND_PORT}" exec npm run dev -- --port "$FRONTEND_PORT"
  ) &
  FRONTEND_PID=$!
fi

ok "Kiwi 已启动："
echo "  前端  http://localhost:${FRONTEND_PORT}"
echo "  后端  http://localhost:${BACKEND_PORT}/docs"
echo "（Ctrl-C 停止）"
wait