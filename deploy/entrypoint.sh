#!/bin/sh
# Kiwi 后端容器入口：先执行数据库迁移，再启动 API。
set -eu

echo "[kiwi] applying database migrations..."
alembic upgrade head

echo "[kiwi] starting API on :8000..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*'
