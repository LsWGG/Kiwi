#!/usr/bin/env bash
# ==============================================================================
# Kiwi 恢复脚本：从 backup.sh / 应用内自动备份生成的目录还原
#
#   ./scripts/restore_backup.sh backups/kiwi-20261021-120000            # Docker 生产栈
#   ./scripts/restore_backup.sh backups/kiwi-20261021-120000 --local    # 宿主机直连
#
# 安全约束：
#   - 恢复会覆盖目标数据库中的同名对象，必须显式追加 --yes 才会执行；
#   - Docker 模式会先停止 backend，恢复完成后重新启动，防止恢复期间继续写入；
#   - 本地模式无法停止进程，请先自行停止后端；
#   - 默认只恢复数据库。附件需追加 --with-uploads；本地模式解压到
#     KIWI_UPLOAD_DIR（默认 backend/data/uploads），会覆盖同名文件。
#
# 可选环境变量：
#   ENV_FILE / COMPOSE_FILE   Docker 模式配置（默认 .env.prod / docker-compose.prod.yml）
#   TARGET_DB                 恢复到的数据库名（默认取配置中的库名）
#   PG_RESTORE / PG_PSQL      本地模式二进制路径
#   KIWI_DATABASE_URL         本地模式数据库连接（也可直接用 PGHOST/PGPORT/...）
#   KIWI_UPLOAD_DIR           本地模式上传目录
#   KIWI_DATA_VOLUME          Docker 数据卷名（默认 kiwi-prod-data）
#   RESTORE_IMAGE             Docker 模式下解压附件使用的镜像（默认 postgres:16-alpine）
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="docker"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"
PG_PSQL="${PG_PSQL:-psql}"
TARGET_DB="${TARGET_DB:-}"
WITH_UPLOADS=0
ASSUME_YES=0

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
}

die() { echo "[kiwi-restore] $*" >&2; exit 1; }
log() { echo "[kiwi-restore] $*"; }

BACKUP_PATH=""
for arg in "$@"; do
  case "$arg" in
    --local) MODE="local" ;;
    --docker) MODE="docker" ;;
    --with-uploads) WITH_UPLOADS=1 ;;
    --yes) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "[kiwi-restore] 未知参数：$arg" >&2; usage >&2; exit 2 ;;
    *)
      [ -z "$BACKUP_PATH" ] || die "只能指定一个备份目录"
      BACKUP_PATH="$arg"
      ;;
  esac
done

[ -n "$BACKUP_PATH" ] || { usage >&2; exit 2; }
[ -d "$BACKUP_PATH" ] || die "备份目录不存在：$BACKUP_PATH"
[ -f "$BACKUP_PATH/db.dump" ] || die "缺少 db.dump：$BACKUP_PATH"
[ -f "$BACKUP_PATH/manifest.json" ] || die "缺少 manifest.json：$BACKUP_PATH"

safe_name() { [[ "$1" =~ ^[A-Za-z0-9_-]+$ ]]; }

compose() {
  "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
  else
    die "未找到 Docker Compose V2；本地模式请使用 --local"
  fi
}

verify_manifest() {
  python3 - "$BACKUP_PATH" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "manifest.json").read_text("utf-8"))
if manifest.get("format") != "kiwi-backup":
    raise SystemExit(f"manifest format 不受支持：{manifest.get('format')!r}")

for entry in manifest.get("files", []):
    name = str(entry.get("name", ""))
    if name not in ("db.dump", "uploads.tar.gz"):
        raise SystemExit(f"manifest 含未知文件：{name}")
    path = root / name
    if not path.is_file():
        raise SystemExit(f"备份缺少文件：{name}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    expected = str(entry.get("sha256", ""))
    if expected and digest.hexdigest() != expected:
        raise SystemExit(f"校验失败：{name} 的 sha256 与 manifest 不一致")

print(
    f"备份 {manifest.get('name')} · {manifest.get('created_at')} · "
    f"数据库 {manifest.get('database', {}).get('database')}"
)
PY
}

load_pg_env() {
  if [ -n "${KIWI_DATABASE_URL:-}" ]; then
    eval "$(python3 - "$KIWI_DATABASE_URL" <<'PY'
import shlex
import sys
import urllib.parse

raw = sys.argv[1].replace("postgresql+asyncpg", "postgresql")
parsed = urllib.parse.urlsplit(raw)
values = {
    "PGHOST": parsed.hostname or "localhost",
    "PGPORT": str(parsed.port or 5432),
    "PGUSER": urllib.parse.unquote(parsed.username or "kiwi"),
    "PGPASSWORD": urllib.parse.unquote(parsed.password or ""),
    "PGDATABASE": (parsed.path or "/kiwi").lstrip("/") or "kiwi",
}
for key, value in values.items():
    print(f"export {key}={shlex.quote(value)}")
PY
)"
  fi
  export PGHOST="${PGHOST:-localhost}"
  export PGPORT="${PGPORT:-5432}"
  export PGUSER="${PGUSER:-kiwi}"
  export PGDATABASE="${PGDATABASE:-kiwi}"
}

restore_local() {
  command -v "$PG_RESTORE" >/dev/null 2>&1 || die "未找到 $PG_RESTORE"
  load_pg_env
  local db="${TARGET_DB:-$PGDATABASE}"
  safe_name "$db" || die "目标数据库名含非法字符"

  echo "[kiwi-restore] 目标：$PGHOST:$PGPORT/$db（本地模式）"
  echo "[kiwi-restore] 数据库恢复会覆盖同名对象，请确认后端已停止写入。"
  if [ "$ASSUME_YES" != 1 ]; then
    read -r -p "输入数据库名 $db 确认恢复：" answer
    [ "$answer" = "$db" ] || die "已取消"
  fi

  "$PG_RESTORE" --clean --if-exists --no-owner --no-acl -d "$db" <"$BACKUP_PATH/db.dump"
  log "数据库恢复完成"

  if [ "$WITH_UPLOADS" = 1 ]; then
    [ -f "$BACKUP_PATH/uploads.tar.gz" ] || die "备份中没有 uploads.tar.gz"
    local upload_dir="${KIWI_UPLOAD_DIR:-$ROOT_DIR/backend/data/uploads}"
    mkdir -p "$upload_dir"
    log "解压附件到 $upload_dir（覆盖同名文件）"
    mkdir -p "$upload_dir"
    tar xzf "$BACKUP_PATH/uploads.tar.gz" -C "$upload_dir"
  else
    log "已跳过附件恢复（追加 --with-uploads 可恢复）"
  fi
}

restore_docker() {
  command -v docker >/dev/null 2>&1 || die "未找到 docker"
  detect_compose
  [ -f "$ENV_FILE" ] || die "未找到 $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  local db_user="${POSTGRES_USER:-kiwi}"
  local db="${TARGET_DB:-${POSTGRES_DB:-kiwi}}"
  local volume="${KIWI_DATA_VOLUME:-kiwi-prod-data}"
  local image="${RESTORE_IMAGE:-postgres:16-alpine}"
  safe_name "$db_user" || die "POSTGRES_USER 含非法字符"
  safe_name "$db" || die "目标数据库名含非法字符"

  echo "[kiwi-restore] 目标：compose postgres / $db（Docker 模式）"
  if [ "$ASSUME_YES" != 1 ]; then
    read -r -p "输入数据库名 $db 确认恢复：" answer
    [ "$answer" = "$db" ] || die "已取消"
  fi

  local was_running=0
  if [ -n "$(compose ps -q backend 2>/dev/null || true)" ]; then
    was_running=1
  fi

  log "停止 backend，避免恢复期间写入"
  compose stop backend >/dev/null 2>&1 || true

  log "断开 $db 的现有连接"
  compose exec -T postgres psql -U "$db_user" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid();" >/dev/null

  log "恢复数据库（pg_restore --clean --if-exists）"
  compose exec -T postgres pg_restore -U "$db_user" -d "$db" \
    --clean --if-exists --no-owner --no-acl <"$BACKUP_PATH/db.dump"
  log "数据库恢复完成"

  if [ "$WITH_UPLOADS" = 1 ]; then
    [ -f "$BACKUP_PATH/uploads.tar.gz" ] || die "备份中没有 uploads.tar.gz"
    log "恢复附件到数据卷 $volume"
    docker run --rm -i -v "$volume:/data" "$image" \
      sh -c 'mkdir -p /data/uploads && tar xzf - -C /data/uploads' \
      <"$BACKUP_PATH/uploads.tar.gz"
  else
    log "已跳过附件恢复（追加 --with-uploads 可恢复）"
  fi

  if [ "$was_running" = 1 ]; then
    log "重新启动 backend"
    compose start backend >/dev/null
  else
    log "backend 原先未运行，未自动启动；可用 ./deploy.sh up 启动"
  fi

  log "提示：数据库已回滚，Qdrant 向量可能滞后。请到 Wiki 页面执行「重建」或重新索引。"
}

log "$(verify_manifest)"

case "$MODE" in
  docker) restore_docker ;;
  local) restore_local ;;
esac

log "恢复流程结束"
