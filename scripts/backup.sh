#!/usr/bin/env bash
# ==============================================================================
# Kiwi 备份脚本（PostgreSQL 自定义格式 + uploads + manifest）
#
#   # Docker 生产栈（默认）：从 docker-compose.prod.yml 的 postgres / backend 容器导出
#   ./scripts/backup.sh
#
#   # 宿主机直连数据库（本地开发 / 无 Docker 环境）
#   ./scripts/backup.sh --local
#
# 可选环境变量：
#   ENV_FILE             .env.prod 文件（默认 .env.prod）
#   COMPOSE_FILE         compose 文件（默认 docker-compose.prod.yml）
#   BACKUP_DIR           备份根目录（默认 <repo>/backups）
#   BACKUP_RETENTION_DAYS 保留天数（默认 14；0 表示不清理）
#   PG_DUMP / PG_RESTORE 指定二进制路径（本地模式）
#   KIWI_DATABASE_URL    本地模式的数据库连接（也可直接用 PGHOST/PGPORT/...）
#   KIWI_UPLOAD_DIR      本地模式的上传目录（默认 backend/data/uploads）
#
# 输出目录结构与后端自动备份一致：
#   backups/kiwi-YYYYmmdd-HHMMSS/
#     db.dump  uploads.tar.gz  manifest.json
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export KIWI_PROJECT_ROOT="$ROOT_DIR"

MODE="docker"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
PG_DUMP="${PG_DUMP:-pg_dump}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"

usage() {
  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --local) MODE="local" ;;
    --docker) MODE="docker" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[kiwi-backup] 未知参数：$arg" >&2; usage >&2; exit 2 ;;
  esac
done

die() { echo "[kiwi-backup] $*" >&2; exit 1; }
log() { echo "[kiwi-backup] $*"; }

need() { command -v "$1" >/dev/null 2>&1 || die "未找到 $1，请先安装"; }

# 只接受字母、数字、下划线与短横线，避免拼接进 SQL / 路径时出现注入。
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

write_manifest() {
  # 参数：目标目录 数据库主机 端口 数据库名 是否包含 uploads
  python3 - "$@" <<'PY'
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
host, port, database, uploads_included = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


project_root = os.environ.get("KIWI_PROJECT_ROOT") or str(target.parent)


def git(*args: str, default: str = "") -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=project_root, stderr=subprocess.DEVNULL, text=True
        ).strip() or default
    except (OSError, subprocess.CalledProcessError):
        return default


files = []
for name in ("db.dump", "uploads.tar.gz"):
    path = target / name
    if path.is_file():
        files.append(
            {"name": name, "size": path.stat().st_size, "sha256": sha256(path)}
        )

manifest = {
    "format": "kiwi-backup",
    "version": 1,
    "name": target.name,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "trigger": "script",
    "app_version": git("describe", "--tags", "--always", default="unknown"),
    "git_commit": git("rev-parse", "--short", "HEAD", default="unknown"),
    "database": {"host": host, "port": port, "database": database},
    "uploads_included": uploads_included,
    "retention_days": int(os.environ.get("RETENTION_DAYS_FOR_MANIFEST", "14")),
    "files": files,
}
(target / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
)
PY
}

prune_old() {
  [ "$RETENTION_DAYS" -gt 0 ] 2>/dev/null || return 0
  [ -d "$BACKUP_DIR" ] || return 0
  while IFS= read -r -d '' dir; do
    base="$(basename "$dir")"
    [[ "$base" == kiwi-* ]] || continue
    [ -f "$dir/manifest.json" ] || continue
    case "$(cd "$dir" && pwd -P)" in
      "$(cd "$BACKUP_DIR" && pwd -P)"/*) ;;
      *) continue ;;
    esac
    log "清理过期备份：$base"
    # 使用 find -delete 而不是 rm -rf，删除范围严格限制在该备份目录内。
    find "$dir" -depth -delete
  done < <(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'kiwi-*' -mtime +"$RETENTION_DAYS" -print0)
}

new_target() {
  mkdir -p "$BACKUP_DIR"
  local stamp target suffix
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  target="$BACKUP_DIR/kiwi-$stamp"
  suffix=1
  while [ -e "$target" ]; do
    suffix=$((suffix + 1))
    target="$BACKUP_DIR/kiwi-$stamp-$suffix"
  done
  mkdir "$target"
  printf '%s' "$target"
}

backup_docker() {
  need docker
  detect_compose
  [ -f "$ENV_FILE" ] || die "未找到 $ENV_FILE；请先复制 .env.prod.example 并填写"
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  local db_user="${POSTGRES_USER:-kiwi}"
  local db_name="${POSTGRES_DB:-kiwi}"
  safe_name "$db_user" || die "POSTGRES_USER 含非法字符"
  safe_name "$db_name" || die "POSTGRES_DB 含非法字符"

  local target tmp
  target="$(new_target)"
  tmp="$target/.tmp"
  mkdir "$tmp"
  trap 'find "$tmp" -depth -delete 2>/dev/null || true; [ -n "${target:-}" ] && [ -z "$(ls -A "$target" 2>/dev/null)" ] && rmdir "$target" 2>/dev/null || true' EXIT

  log "导出数据库 $db_name → $target/db.dump"
  compose exec -T postgres pg_dump -U "$db_user" -d "$db_name" \
    --format=custom --no-owner --no-acl >"$tmp/db.dump"
  [ -s "$tmp/db.dump" ] || die "pg_dump 输出为空"

  local uploads=0
  if compose exec -T backend test -d /app/data/uploads >/dev/null 2>&1; then
    log "打包 uploads → $target/uploads.tar.gz"
    compose exec -T backend tar czf - -C /app/data/uploads . >"$tmp/uploads.tar.gz"
    uploads=1
  else
    log "容器内未找到 /app/data/uploads，跳过附件归档"
  fi

  mv "$tmp"/* "$target"/
  rmdir "$tmp"
  trap - EXIT
  export RETENTION_DAYS_FOR_MANIFEST="$RETENTION_DAYS"
  write_manifest "$target" "postgres" "5432" "$db_name" "$uploads"
  unset RETENTION_DAYS_FOR_MANIFEST
  log "备份完成：$target"
  prune_old
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

backup_local() {
  need "$PG_DUMP"
  load_pg_env
  safe_name "$PGDATABASE" || die "数据库名含非法字符"

  local target tmp
  target="$(new_target)"
  tmp="$target/.tmp"
  mkdir "$tmp"
  trap 'find "$tmp" -depth -delete 2>/dev/null || true' EXIT

  log "导出数据库 $PGDATABASE（$PGHOST:$PGPORT）→ $target/db.dump"
  "$PG_DUMP" --format=custom --no-owner --no-acl >"$tmp/db.dump"
  [ -s "$tmp/db.dump" ] || die "pg_dump 输出为空"

  local upload_dir="${KIWI_UPLOAD_DIR:-$ROOT_DIR/backend/data/uploads}"
  local uploads=0
  if [ -d "$upload_dir" ]; then
    log "打包 $upload_dir → $target/uploads.tar.gz"
    tar czf "$tmp/uploads.tar.gz" -C "$upload_dir" .
    uploads=1
  else
    log "未找到 $upload_dir，跳过附件归档"
  fi

  mv "$tmp"/* "$target"/
  rmdir "$tmp"
  trap - EXIT
  export RETENTION_DAYS_FOR_MANIFEST="$RETENTION_DAYS"
  write_manifest "$target" "$PGHOST" "$PGPORT" "$PGDATABASE" "$uploads"
  unset RETENTION_DAYS_FOR_MANIFEST
  log "备份完成：$target"
  prune_old
}

case "$MODE" in
  docker) backup_docker ;;
  local) backup_local ;;
esac
