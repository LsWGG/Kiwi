#!/usr/bin/env bash
# ==============================================================================
# Kiwi Docker 生产部署脚本
#
#   ./deploy.sh                 交互式部署：按需询问访问地址、访问令牌、前端构建、
#                               Cloudflare 隧道与升级前备份
#   ./deploy.sh --yes           非交互部署（使用 .env.prod 中已有配置）
#   ./deploy.sh update          按最新源码与环境变量重建 backend 容器
#   ./deploy.sh frontend        仅构建前端（宿主机 npm run build）
#   ./deploy.sh cloudflare      配置并启动 Cloudflare Tunnel（询问 Token / 域名）
#   ./deploy.sh cloudflare off  停止公网隧道
#   ./deploy.sh cloudflare status
#   ./deploy.sh ps              查看状态
#   ./deploy.sh logs [svc]      跟踪日志
#   ./deploy.sh restart         重启全部服务
#   ./deploy.sh down            停止（保留数据卷）
#
# 选项（可放在子命令前后）：
#   -y, --yes          不询问，使用现有 .env.prod 与已保存的隧道开关
#   --cloudflare       本次强制启用 Cloudflare Tunnel（需已配置 Token）
#   --no-cloudflare    本次强制不启动 Cloudflare Tunnel
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env.prod"
COMPOSE_FILE="docker-compose.prod.yml"

ASSUME_YES=0
FORCE_CLOUDFLARE=""
CMD=""
ARGS=()
COMPOSE_CMD=()
PROFILE_ARGS=()

BUILD_FRONTEND=0
DO_BACKUP=0
CLOUDFLARE_ENABLED=0
HAD_ENV=0

die() { echo "[kiwi-deploy] $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Kiwi Docker 生产部署脚本

  ./deploy.sh                 交互式部署（首次部署 / 完整更新）
  ./deploy.sh --yes           非交互部署，直接使用 .env.prod 现有配置
  ./deploy.sh update          重建 backend 容器，加载新代码与环境变量
  ./deploy.sh frontend        仅构建前端
  ./deploy.sh cloudflare      配置并启动 Cloudflare Tunnel
  ./deploy.sh cloudflare off  停止公网隧道
  ./deploy.sh cloudflare status
  ./deploy.sh ps              查看状态
  ./deploy.sh logs [svc]      跟踪日志
  ./deploy.sh restart         重启全部服务
  ./deploy.sh down            停止（保留数据卷）
  ./deploy.sh build           构建前端与后端镜像

选项（可放在子命令前后）：
  -y, --yes          不询问
  --cloudflare       本次强制启用 Cloudflare Tunnel
  --no-cloudflare    本次强制不启动 Cloudflare Tunnel
EOF
}

gen_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c1-24
  else
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n' | cut -c1-24
  fi
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

gen_access_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

# 原子地更新 / 追加 .env.prod 中的键；值通过环境变量传给 awk，避免转义问题。
env_set() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${TMPDIR:-/tmp}/kiwi-env.XXXXXX")"
  KIWI_ENV_VALUE="$value" awk -v key="$key" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 {
      if (!found) { print key "=" ENVIRON["KIWI_ENV_VALUE"]; found = 1 }
      next
    }
    { print }
    END { if (!found) print key "=" ENVIRON["KIWI_ENV_VALUE"] }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  KIWI_HTTP_PORT="${KIWI_HTTP_PORT:-18473}"
  KIWI_API_PORT="${KIWI_API_PORT:-18474}"
  case "$KIWI_HTTP_PORT" in
    ''|*[!0-9]*) die "KIWI_HTTP_PORT 必须是数字（当前：$KIWI_HTTP_PORT）" ;;
  esac
  KIWI_PUBLIC_ORIGIN="${KIWI_PUBLIC_ORIGIN:-http://localhost:${KIWI_HTTP_PORT}}"
  KIWI_PUBLIC_BASE_URL="${KIWI_PUBLIC_BASE_URL:-}"
  KIWI_ACCESS_TOKEN="${KIWI_ACCESS_TOKEN:-}"
  CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
  KIWI_CLOUDFLARE_ENABLED="${KIWI_CLOUDFLARE_ENABLED:-false}"
}

ensure_env() {
  if [ ! -f "$ENV_FILE" ]; then
    [ -f .env.prod.example ] || die "缺少 .env.prod.example，无法生成 $ENV_FILE"
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

is_interactive() {
  [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]
}

# ---- 提示符：提示写 stderr，结果写 stdout，方便 $(...) 捕获 ----

ask() {
  local prompt="$1" default="${2:-}" answer=""
  printf '%s' "$prompt" >&2
  if [ -n "$default" ]; then
    printf ' [%s]: ' "$default" >&2
  else
    printf ': ' >&2
  fi
  read -r answer || true
  printf '%s\n' "${answer:-$default}"
}

ask_secret() {
  local prompt="$1" answer=""
  printf '%s: ' "$prompt" >&2
  read -r -s answer || true
  printf '\n' >&2
  printf '%s\n' "$answer"
}

ask_yes_no() {
  local prompt="$1" default="${2:-n}" answer hint
  case "$default" in
    y|Y) hint="Y/n" ;;
    *) hint="y/N" ;;
  esac
  while :; do
    printf '%s [%s]: ' "$prompt" "$hint" >&2
    read -r answer || true
    answer="${answer:-$default}"
    case "$answer" in
      y|Y|yes|YES|是) return 0 ;;
      n|N|no|NO|否) return 1 ;;
      *) echo "  请输入 y 或 n。" >&2 ;;
    esac
  done
}

# ---- 环境探测 ----

is_true() {
  case "${1:-}" in
    true|TRUE|True|1|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

detect_lan_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '
      { for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }
    ' || true)"
  fi
  if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  fi
  printf '%s' "$ip"
}

valid_origin() {
  # 只接受可直接写入 .env.prod 的 URL 字符，避免 shell 解析问题。
  [[ "$1" =~ ^https?://[A-Za-z0-9._-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?$ ]]
}

valid_public_base() {
  [[ "$1" =~ ^https://[A-Za-z0-9._-]+(:[0-9]+)?$ ]]
}

valid_cf_token() {
  [[ "$1" =~ ^[A-Za-z0-9+/=._-]+$ ]]
}

url_host() {
  local host="${1#*://}"
  host="${host%%/*}"
  printf '%s' "$host"
}

is_local_host() {
  case "$1" in
    localhost|localhost:*|127.0.0.1|127.0.0.1:*|\[::1\]|\[::1\]:*|::1) return 0 ;;
    *) return 1 ;;
  esac
}

port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
}

stack_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'kiwi-prod-frontend'
}

postgres_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'kiwi-prod-postgres'
}

cloudflared_exists() {
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'kiwi-prod-cloudflared'
}

cloudflared_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'kiwi-prod-cloudflared'
}

published_web_port() {
  docker port kiwi-prod-frontend 80 2>/dev/null | head -n 1 | sed 's/.*://' || true
}

# 后端 Dockerfile 使用 RUN --mount=type=cache 复用依赖缓存，必须启用 BuildKit。
# 显式导出可覆盖宿主机 / daemon 中 DOCKER_BUILDKIT=0 的配置。
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

compose() {
  if [ "${#PROFILE_ARGS[@]}" -gt 0 ]; then
    "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "${PROFILE_ARGS[@]}" "$@"
  else
    "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  fi
}

compose_cloudflare() {
  "${COMPOSE_CMD[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile cloudflare "$@"
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

# ---- 交互式向导 ----

prompt_new_access_token() {
  local token
  while :; do
    token="$(ask_secret '访问令牌（留空自动生成，至少 8 位）')"
    if [ -z "$token" ]; then
      token="$(gen_access_token)"
      echo "  已自动生成访问令牌。" >&2
      break
    fi
    if [ "${#token}" -lt 8 ]; then
      echo "  令牌至少 8 位，请重新输入。" >&2
      continue
    fi
    case "$token" in
      *[!A-Za-z0-9._~-]*)
        echo "  令牌仅支持字母、数字和 . _ ~ -，请重新输入。" >&2
        continue
        ;;
    esac
    break
  done
  env_set KIWI_ACCESS_TOKEN "$token"
  KIWI_ACCESS_TOKEN="$token"
  echo "  访问令牌已写入 $ENV_FILE（KIWI_ACCESS_TOKEN）。"
}

configure_cloudflare() {
  local token base default_base
  token="${CLOUDFLARE_TUNNEL_TOKEN:-}"
  if [ -n "$token" ]; then
    if ! ask_yes_no "保留现有 Cloudflare Tunnel Token？" y; then
      token=""
    elif ! valid_cf_token "$token"; then
      echo "  现有 Token 格式异常，请重新输入。" >&2
      token=""
    fi
  fi
  if [ -z "$token" ]; then
    while :; do
      token="$(ask_secret 'Cloudflare Tunnel Token（Zero Trust → Networks → Tunnels）')"
      if [ -z "$token" ]; then
        echo "  Token 不能为空。" >&2
        continue
      fi
      if ! valid_cf_token "$token"; then
        echo "  Token 含有不支持字符，请重新复制。" >&2
        continue
      fi
      break
    done
  fi
  env_set CLOUDFLARE_TUNNEL_TOKEN "$token"
  CLOUDFLARE_TUNNEL_TOKEN="$token"

  default_base="${KIWI_PUBLIC_BASE_URL:-}"
  echo "公网分享链接会使用这个域名，只填协议 + 域名，例如 https://share.example.com。" >&2
  while :; do
    base="$(ask '公网分享域名' "$default_base")"
    base="${base%/}"
    if [ -z "$base" ]; then
      echo "  启用隧道时必须填写公网域名，用于生成分享链接。" >&2
      continue
    fi
    if valid_public_base "$base"; then break; fi
    echo "  需要 https:// 开头，且不要带路径、参数。" >&2
  done
  env_set KIWI_PUBLIC_BASE_URL "$base"
  KIWI_PUBLIC_BASE_URL="$base"
}

wizard_up() {
  local current_origin lan_ip default_origin old_port new_port owned_port answer
  local cf_default

  echo
  echo "[kiwi-deploy] 交互式部署向导（直接回车使用方括号中的默认值）"

  # 1. Web 端口：仅当端口被其他程序占用时询问，避免打断正常更新。
  old_port="$KIWI_HTTP_PORT"
  owned_port=""
  if stack_running; then
    owned_port="$(published_web_port)"
  fi
  if port_in_use "$KIWI_HTTP_PORT" && [ "$owned_port" != "$KIWI_HTTP_PORT" ]; then
    echo
    echo "端口 ${KIWI_HTTP_PORT} 已被其他程序占用。"
    new_port="$((KIWI_HTTP_PORT + 1))"
    while :; do
      answer="$(ask 'Web 端口' "$new_port")"
      case "$answer" in
        ''|*[!0-9]*) echo "  请输入 1-65535 的数字。" >&2; continue ;;
      esac
      if [ "$answer" -lt 1 ] || [ "$answer" -gt 65535 ]; then
        echo "  端口超出范围。" >&2
        continue
      fi
      if port_in_use "$answer"; then
        echo "  端口 $answer 仍被占用。" >&2
        continue
      fi
      break
    done
    if [ "$answer" != "$old_port" ]; then
      env_set KIWI_HTTP_PORT "$answer"
      KIWI_HTTP_PORT="$answer"
    fi
  fi

  # 2. 浏览器访问地址（CORS / 分享链接回退地址）。
  current_origin="${KIWI_PUBLIC_ORIGIN%/}"
  if [ "$KIWI_HTTP_PORT" != "$old_port" ]; then
    case "$current_origin" in
      "http://localhost:$old_port"|"http://127.0.0.1:$old_port")
        current_origin="http://localhost:${KIWI_HTTP_PORT}"
        ;;
      *":$old_port")
        current_origin="${current_origin%:$old_port}:${KIWI_HTTP_PORT}"
        ;;
    esac
  fi
  lan_ip="$(detect_lan_ip)"
  if is_local_host "$(url_host "$current_origin")" && [ -n "$lan_ip" ]; then
    default_origin="http://${lan_ip}:${KIWI_HTTP_PORT}"
  else
    default_origin="$current_origin"
  fi
  echo
  echo "访问地址用于 CORS 与文档示例；局域网部署建议填服务器 IP。"
  while :; do
    answer="$(ask '浏览器访问地址' "$default_origin")"
    answer="${answer%/}"
    if valid_origin "$answer"; then break; fi
    echo "  需要以 http:// 或 https:// 开头的完整地址。" >&2
  done
  if [ "$answer" != "$KIWI_PUBLIC_ORIGIN" ]; then
    env_set KIWI_PUBLIC_ORIGIN "$answer"
    KIWI_PUBLIC_ORIGIN="$answer"
  fi

  # 3. 访问令牌。
  echo
  if [ -n "${KIWI_ACCESS_TOKEN:-}" ]; then
    echo "访问令牌当前已启用。"
    while :; do
      answer="$(ask '令牌处理（1=保留 2=更换 3=关闭）' '1')"
      case "$answer" in
        1) break ;;
        2) prompt_new_access_token; break ;;
        3)
          env_set KIWI_ACCESS_TOKEN ""
          KIWI_ACCESS_TOKEN=""
          echo "  已关闭访问令牌。"
          break
          ;;
        *) echo "  请输入 1、2 或 3。" >&2 ;;
      esac
    done
  else
    local token_default=n
    if ! is_local_host "$(url_host "$KIWI_PUBLIC_ORIGIN")"; then
      token_default=y
    fi
    if ask_yes_no "启用访问令牌（浏览器首次访问需输入）？" "$token_default"; then
      prompt_new_access_token
    fi
  fi

  # 4. Cloudflare Tunnel（只暴露分享页与公开分享 API）。
  echo
  echo "公网只读分享：Cloudflare Tunnel 只暴露 /share/、/api/share/、/assets/、/favicon。"
  cf_default=n
  if is_true "$KIWI_CLOUDFLARE_ENABLED"; then
    cf_default=y
  fi
  if [ -n "$FORCE_CLOUDFLARE" ]; then
    if [ "$FORCE_CLOUDFLARE" = 1 ]; then
      cf_default=y
    else
      cf_default=n
    fi
  elif ask_yes_no "启用 Cloudflare Tunnel 公网分享？" "$cf_default"; then
    cf_default=y
  else
    cf_default=n
  fi

  if [ "$cf_default" = y ]; then
    configure_cloudflare
    env_set KIWI_CLOUDFLARE_ENABLED true
    KIWI_CLOUDFLARE_ENABLED=true
  else
    env_set KIWI_CLOUDFLARE_ENABLED false
    KIWI_CLOUDFLARE_ENABLED=false
    if cloudflared_running; then
      if ask_yes_no "检测到 cloudflared 容器正在运行，停止它？" y; then
        compose_cloudflare stop cloudflared >/dev/null 2>&1 || true
        echo "  已停止 cloudflared。"
      else
        echo "  cloudflared 仍在运行，公网分享仍可访问；稍后可执行 ./deploy.sh cloudflare off 停止。" >&2
      fi
    fi
  fi

  # 5. 前端构建与备份。
  echo
  if [ -f frontend/dist/index.html ]; then
    if ask_yes_no "重新构建前端（确保与当前代码一致）？" y; then
      BUILD_FRONTEND=1
    fi
  else
    BUILD_FRONTEND=1
  fi

  if postgres_running && [ -x scripts/backup.sh ]; then
    if ask_yes_no "部署前备份数据库与上传文件？" y; then
      DO_BACKUP=1
    fi
  fi
}

apply_cloudflare() {
  local persist="${1:-0}" require_token="${2:-1}" enabled
  enabled="${KIWI_CLOUDFLARE_ENABLED:-false}"

  if [ -n "$FORCE_CLOUDFLARE" ]; then
    if [ "$FORCE_CLOUDFLARE" = 1 ]; then
      enabled=true
    else
      enabled=false
    fi
  fi

  # 先校验再写文件：避免部署失败却在 .env.prod 里留下「已启用」。
  if is_true "$enabled" && [ "$require_token" = 1 ]; then
    [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] || die "已启用 Cloudflare Tunnel，但 CLOUDFLARE_TUNNEL_TOKEN 为空。请运行 ./deploy.sh cloudflare 配置，或在 $ENV_FILE 中填写。"
    valid_cf_token "$CLOUDFLARE_TUNNEL_TOKEN" || die "CLOUDFLARE_TUNNEL_TOKEN 含有不支持字符，请重新复制。"
  fi

  if [ -n "$FORCE_CLOUDFLARE" ] && [ "$persist" = 1 ]; then
    KIWI_CLOUDFLARE_ENABLED="$enabled"
    env_set KIWI_CLOUDFLARE_ENABLED "$enabled"
    if [ "$FORCE_CLOUDFLARE" = 1 ]; then
      # 显式启用时把本次环境变量中的配置一并落盘，后续 up 不再依赖临时变量。
      if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
        env_set CLOUDFLARE_TUNNEL_TOKEN "$CLOUDFLARE_TUNNEL_TOKEN"
      fi
      if [ -n "${KIWI_PUBLIC_BASE_URL:-}" ]; then
        env_set KIWI_PUBLIC_BASE_URL "$KIWI_PUBLIC_BASE_URL"
      fi
    elif cloudflared_running; then
      echo "[kiwi-deploy] 停止 cloudflared 容器…"
      compose_cloudflare stop cloudflared >/dev/null 2>&1 || true
    fi
  fi

  PROFILE_ARGS=()
  CLOUDFLARE_ENABLED=0
  if is_true "$enabled"; then
    if [ -z "${KIWI_PUBLIC_BASE_URL:-}" ]; then
      echo "[kiwi-deploy] 警告：KIWI_PUBLIC_BASE_URL 为空，分享链接可能使用内网地址。" >&2
    fi
    PROFILE_ARGS=(--profile cloudflare)
    CLOUDFLARE_ENABLED=1
  fi
}

print_summary() {
  local token_state cf_state
  if [ -n "${KIWI_ACCESS_TOKEN:-}" ]; then
    token_state="已启用"
  else
    token_state="未启用"
  fi
  if [ "$CLOUDFLARE_ENABLED" = 1 ]; then
    cf_state="启用 → ${KIWI_PUBLIC_BASE_URL:-（未配置域名）}"
  else
    cf_state="未启用"
  fi

  echo
  echo "部署摘要"
  echo "  访问地址   ${KIWI_PUBLIC_ORIGIN}"
  echo "  Web 端口   ${KIWI_HTTP_PORT}"
  echo "  访问令牌   ${token_state}"
  echo "  Cloudflare ${cf_state}"
  if [ "$BUILD_FRONTEND" = 1 ]; then
    echo "  前端构建   是"
  else
    echo "  前端构建   否（使用现有 dist）"
  fi
}

print_cloudflare_hints() {
  local host="${KIWI_PUBLIC_BASE_URL#*://}"
  host="${host%%/*}"
  echo
  echo "[kiwi-deploy] Cloudflare Tunnel 已启动（cloudflared 容器）"
  echo "  在 Cloudflare Zero Trust → Networks → Tunnels → 你的隧道 → Public Hostname 添加："
  echo "    ${host:-<分享域名>}  /share/      →  http://frontend:80"
  echo "    ${host:-<分享域名>}  /api/share/  →  http://frontend:80"
  echo "    ${host:-<分享域名>}  /assets/     →  http://frontend:80"
  echo "    ${host:-<分享域名>}  /favicon     →  http://frontend:80"
  echo "  其余路径默认 404；修改 Token / 域名可重新运行 ./deploy.sh cloudflare。"
  echo "  查看隧道日志：./deploy.sh logs cloudflared"
}

run_up() {
  HAD_ENV=0
  if [ -f "$ENV_FILE" ]; then
    HAD_ENV=1
  fi

  ensure_env
  load_env

  if is_interactive; then
    if [ "$HAD_ENV" = 0 ]; then
      echo "[kiwi-deploy] 首次部署：已生成随机数据库密码与 Fernet 密钥。"
    fi
    wizard_up
    load_env
  else
    echo "[kiwi-deploy] 非交互模式：使用 $ENV_FILE 中已有配置。"
    BUILD_FRONTEND=0
    DO_BACKUP=0
  fi

  if [ ! -f frontend/dist/index.html ]; then
    BUILD_FRONTEND=1
  fi

  apply_cloudflare 1 1
  print_summary

  if is_interactive; then
    if ! ask_yes_no "确认开始部署？" y; then
      echo "[kiwi-deploy] 已取消部署；向导中的配置已保存到 $ENV_FILE。"
      exit 0
    fi
  fi

  if [ "$DO_BACKUP" = 1 ]; then
    echo "[kiwi-deploy] 部署前备份…"
    ./scripts/backup.sh
  fi

  if [ "$BUILD_FRONTEND" = 1 ]; then
    build_frontend
  else
    ensure_frontend_dist
  fi

  ensure_buildkit
  compose up -d --build
  load_env

  echo
  echo "[kiwi-deploy] Kiwi 已启动"
  echo "  Web   ${KIWI_PUBLIC_ORIGIN}"
  echo "  API   http://localhost:${KIWI_API_PORT}/docs"
  if [ "$CLOUDFLARE_ENABLED" = 1 ]; then
    echo "  公网分享 ${KIWI_PUBLIC_BASE_URL}"
    print_cloudflare_hints
  fi
  echo "  数据卷 kiwi-prod-pgdata / kiwi-prod-qdrantdata / kiwi-prod-data"
}

run_cloudflare() {
  local sub="enable"
  if [ "${#ARGS[@]}" -gt 0 ]; then
    sub="${ARGS[0]}"
  fi

  ensure_env
  load_env

  case "$sub" in
    off|disable|stop)
      env_set KIWI_CLOUDFLARE_ENABLED false
      if cloudflared_exists; then
        compose_cloudflare stop cloudflared || true
      fi
      echo "[kiwi-deploy] Cloudflare Tunnel 已停止；Token 与分享域名保留在 $ENV_FILE。"
      ;;
    status)
      echo "  KIWI_CLOUDFLARE_ENABLED=${KIWI_CLOUDFLARE_ENABLED}"
      echo "  KIWI_PUBLIC_BASE_URL=${KIWI_PUBLIC_BASE_URL:-（未配置）}"
      compose_cloudflare ps cloudflared || true
      ;;
    enable|on)
      if is_interactive; then
        configure_cloudflare
      else
        [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] || die "未配置 CLOUDFLARE_TUNNEL_TOKEN；请先在 $ENV_FILE 中填写，或在交互终端运行 ./deploy.sh cloudflare。"
        valid_cf_token "$CLOUDFLARE_TUNNEL_TOKEN" || die "CLOUDFLARE_TUNNEL_TOKEN 含有不支持字符，请重新复制。"
        [ -n "${KIWI_PUBLIC_BASE_URL:-}" ] || die "未配置 KIWI_PUBLIC_BASE_URL；请先在 $ENV_FILE 中填写公网分享域名。"
        valid_public_base "$KIWI_PUBLIC_BASE_URL" || die "KIWI_PUBLIC_BASE_URL 必须是 https:// 域名（不含路径、参数），例如 https://share.example.com。"
        # 非交互模式也把本次提供的配置落盘，后续 up / status 才能复用。
        env_set CLOUDFLARE_TUNNEL_TOKEN "$CLOUDFLARE_TUNNEL_TOKEN"
        env_set KIWI_PUBLIC_BASE_URL "$KIWI_PUBLIC_BASE_URL"
      fi
      env_set KIWI_CLOUDFLARE_ENABLED true
      KIWI_CLOUDFLARE_ENABLED=true
      load_env
      PROFILE_ARGS=(--profile cloudflare)
      # 重建 backend 让新的 KIWI_PUBLIC_BASE_URL 生效，同时启动 cloudflared。
      compose up -d backend cloudflared
      print_cloudflare_hints
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

# ---- 参数解析 ----

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
  esac
  if [ "$CMD" = "logs" ]; then
    ARGS+=("$1")
    shift
    continue
  fi
  case "$1" in
    -y|--yes) ASSUME_YES=1; shift ;;
    --cloudflare) FORCE_CLOUDFLARE=1; shift ;;
    --no-cloudflare) FORCE_CLOUDFLARE=0; shift ;;
    --)
      shift
      while [ $# -gt 0 ]; do
        if [ -z "$CMD" ]; then
          CMD="$1"
        else
          ARGS+=("$1")
        fi
        shift
      done
      break
      ;;
    -*) die "未知参数：$1（使用 --help 查看用法）" ;;
    *)
      if [ -z "$CMD" ]; then
        CMD="$1"
      else
        ARGS+=("$1")
      fi
      shift
      ;;
  esac
done
CMD="${CMD:-up}"

# ---- 运行环境 ----

# 构建版本同时写入前端 build-info.json 与后端镜像环境变量，供设置页做一致性检查。
KIWI_BUILD_COMMIT="${KIWI_BUILD_COMMIT:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
KIWI_BUILD_TIME="${KIWI_BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
export KIWI_BUILD_COMMIT KIWI_BUILD_TIME
echo "[kiwi-deploy] 构建版本：${KIWI_BUILD_COMMIT} @ ${KIWI_BUILD_TIME}"

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

case "$CMD" in
  up|start)
    run_up
    ;;
  down|stop)
    ensure_env
    load_env
    apply_cloudflare 0 0
    # down 时把已存在的 cloudflared 也纳入项目，避免留下孤立容器。
    if cloudflared_exists; then
      PROFILE_ARGS=(--profile cloudflare)
    fi
    compose down
    echo "[kiwi-deploy] 已停止（数据卷保留）"
    ;;
  update|reload)
    ensure_env
    load_env
    apply_cloudflare 0 0
    # 后端源码以 bind mount 运行，但环境变量变更需要重建容器才能生效。
    compose up -d backend
    echo "[kiwi-deploy] backend 已按最新源码与环境变量重建"
    ;;
  restart)
    ensure_env
    load_env
    apply_cloudflare 0 0
    compose restart
    ;;
  ps|status)
    ensure_env
    load_env
    apply_cloudflare 0 0
    compose ps
    ;;
  logs)
    ensure_env
    load_env
    apply_cloudflare 0 0
    # 即使隧道开关关闭，也允许直接查看已存在容器的日志。
    if [ "${#ARGS[@]}" -gt 0 ]; then
      for log_arg in "${ARGS[@]}"; do
        if [ "$log_arg" = "cloudflared" ]; then
          PROFILE_ARGS=(--profile cloudflare)
          break
        fi
      done
    fi
    if [ "${#ARGS[@]}" -gt 0 ]; then
      compose logs -f --tail=200 "${ARGS[@]}"
    else
      compose logs -f --tail=200
    fi
    ;;
  frontend)
    build_frontend
    ;;
  build)
    ensure_env
    load_env
    apply_cloudflare 0 0
    build_frontend
    ensure_buildkit
    compose build
    ;;
  cloudflare|cf|tunnel)
    run_cloudflare
    ;;
  *)
    usage
    exit 1
    ;;
esac
