#!/usr/bin/env bash
# ==============================================================================
# 生成后端 .env（无 docker 依赖版本）
# 用法：POSTGRES_PASSWORD=xxx bash scripts/gen_env.sh
# 安全：Fernet/SECRET 随机生成；DB 凭据从环境变量取，不硬编码。
# 已存在 .env 则跳过（不覆盖）。
# ==============================================================================
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f .env ]; then
  echo "[gen-env] .env 已存在，跳过。如需重生成请删除后重跑。"
  exit 0
fi
[ -f .env.example ] || { echo ".env.example 缺失"; exit 1; }

PG_USER="${POSTGRES_USER:-postgres}"
PG_PASS="${POSTGRES_PASSWORD:-}"
PG_DB="${POSTGRES_DB:-postgres}"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"

# 生成 Fernet / SECRET（优先用 backend venv 内的 cryptography）
PYTHON="${ROOT_DIR}/backend/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON=python3; fi
if ! "$PYTHON" -c 'import cryptography' 2>/dev/null; then
  echo "缺少 cryptography，尝试用 uv 临时环境生成 Fernet 密钥…"
  FERNET_KEY="$(uv run --with cryptography python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
else
  FERNET_KEY="$("$PYTHON" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
fi
SECRET="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"

cat > .env <<EOF
# Kiwi 本地配置（由 scripts/gen_env.sh 生成）
POSTGRES_USER=${PG_USER}
POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_DB=${PG_DB}
POSTGRES_PORT=${PG_PORT}
QDRANT_PORT=6333
REDIS_PORT=6379

KIWI_DATABASE_URL=postgresql+asyncpg://${PG_USER}:${PG_PASS}@${PG_HOST}:${PG_PORT}/${PG_DB}
KIWI_QDRANT_URL=http://localhost:6333
KIWI_REDIS_URL=redis://localhost:6379/0

KIWI_FERNET_KEY=${FERNET_KEY}
SECRET_KEY=${SECRET}
EOF
chmod 600 .env
echo "[gen-env] ✅ .env 已生成（chmod 600）"