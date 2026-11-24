#!/usr/bin/env bash
# 线上一键更新：本地构建前端 → 上传 dist → 远端拉取后端代码并重建。
#
# 连接配置从 scripts/update_online.env 读取（该文件已被 .gitignore 忽略），
# 也可用环境变量覆盖。首次使用：
#   cp scripts/update_online.env.example scripts/update_online.env
#   # 填入 KIWI_DEPLOY_HOST / PORT / USER / PATH
#
# 用法：
#   ./scripts/update_online.sh                 # 后端 + 前端
#   ./scripts/update_online.sh --backend-only  # 只更新后端
#   ./scripts/update_online.sh --frontend-only # 只构建并上传前端
#   ./scripts/update_online.sh --skip-build    # 复用现有 frontend/dist
#   ./scripts/update_online.sh --build-backend # 先重建后端镜像（依赖变化时使用）
#   ./scripts/update_online.sh --dry-run       # 只打印将执行的命令
#
# 安全约束：
# - 前端构建默认要求本地 HEAD == origin/main 且工作区干净，避免把未提交改动
#   传到线上；确需如此时加 --allow-dirty（会显著提示版本风险）。
# - 远端后端使用 `git pull --ff-only`，不会产生合并提交；GitHub 偶发连接
#   失败时最多重试 5 次，仍失败则中止。
# - 远端旧 dist 在覆盖前不会自动备份；脚本会打印远端提交号，便于回滚。

set -euo pipefail

REMOTE_HOST=""
REMOTE_PORT=""
REMOTE_USER=""
REMOTE_PATH=""
REF="${KIWI_DEPLOY_REF:-origin/main}"

BACKEND=1
FRONTEND=1
SKIP_BUILD=0
BUILD_BACKEND=0
ALLOW_DIRTY=0
DRY_RUN=0
ASSUME_YES=0

usage() {
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

while (($#)); do
  case "$1" in
    --backend-only) BACKEND=1; FRONTEND=0 ;;
    --frontend-only) BACKEND=0; FRONTEND=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --build-backend) BUILD_BACKEND=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${KIWI_DEPLOY_ENV:-$ROOT/scripts/update_online.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
REMOTE_HOST="${KIWI_DEPLOY_HOST:-}"
REMOTE_PORT="${KIWI_DEPLOY_PORT:-22}"
REMOTE_USER="${KIWI_DEPLOY_USER:-}"
REMOTE_PATH="${KIWI_DEPLOY_PATH:-}"
[[ -n "$REMOTE_HOST" && -n "$REMOTE_USER" && -n "$REMOTE_PATH" ]] || {
  printf '\033[1;31m[kiwi]\033[0m 缺少部署配置：请创建 %s（可复制 .example）\n' "$ENV_FILE" >&2
  exit 2
}
SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SSH_OPTS=(-p "$REMOTE_PORT" -o ConnectTimeout=10)
DIST="$ROOT/frontend/dist"

log() { printf '\033[1;36m[kiwi]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[kiwi]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[kiwi]\033[0m %s\n' "$*" >&2; exit 1; }

run() {
  if ((DRY_RUN)); then
    printf '  $'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

remote() {
  if ((DRY_RUN)); then
    printf '  [remote] %s\n' "$*"
  else
    ssh -t "${SSH_OPTS[@]}" "$SSH_TARGET" "$@"
  fi
}

remote_capture() {
  ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$@"
}

# ---------- 前置检查 ----------
command -v git >/dev/null || fail "缺少 git"
if ((BACKEND)); then
  command -v ssh >/dev/null || fail "缺少 ssh"
fi
if ((FRONTEND)); then
  command -v npm >/dev/null || fail "缺少 npm"
  command -v rsync >/dev/null || fail "缺少 rsync"
fi

if ((FRONTEND)) && ((SKIP_BUILD == 0)); then
  log "检查本地仓库状态"
  git fetch origin main --quiet
  local_head="$(git rev-parse --short HEAD)"
  remote_head="$(git rev-parse --short "$REF")"
  if ((DRY_RUN == 0)); then
    if [[ "$local_head" != "$remote_head" ]]; then
      fail "本地 HEAD ($local_head) 与 $REF ($remote_head) 不一致；请先提交/合并并推送，或使用 --skip-build"
    fi
    if [[ -n "$(git status --porcelain)" ]] && ((ALLOW_DIRTY == 0)); then
      fail "工作区有未提交改动；请先提交，或使用 --allow-dirty（不推荐）"
    fi
    if ((ALLOW_DIRTY)) && [[ -n "$(git status --porcelain)" ]]; then
      warn "使用 --allow-dirty：前端构建包含未提交改动，线上后端仍是 $REF，可能出现版本不一致"
    fi
  else
    log "dry-run：跳过干净检查（本地 $local_head / $REF $remote_head）"
  fi
fi

if ((SKIP_BUILD == 0)) && ((FRONTEND)); then
  if [[ ! -d "$ROOT/frontend/node_modules" && $DRY_RUN -eq 0 ]]; then
    log "安装前端依赖（npm ci）"
    (cd "$ROOT/frontend" && npm ci)
  fi
  log "构建前端"
  if ((DRY_RUN)); then
    run bash -lc "cd '$ROOT/frontend' && npm run build"
  else
    (cd "$ROOT/frontend" && npm run build)
  fi
fi

if ((FRONTEND)); then
  [[ -f "$DIST/build-info.json" ]] || fail "缺少 $DIST/build-info.json；请先构建前端"
fi

log "目标：$SSH_TARGET:$REMOTE_PATH"
if ((BACKEND)); then
  if ((BUILD_BACKEND)); then
    log "后端：sudo git pull --ff-only && 重建 backend 镜像 && sudo ./deploy.sh update"
  else
    log "后端：sudo git pull --ff-only && sudo ./deploy.sh update"
  fi
fi
((FRONTEND)) && log "前端：上传 $DIST → frontend/dist，重启 frontend 容器"

if ((DRY_RUN == 0 && ASSUME_YES == 0)); then
  read -r -p "确认执行？[y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "已取消"; exit 1; }
fi

# ---------- 后端 ----------
if ((BACKEND)); then
  log "更新后端"
  # 远端到 GitHub 的连通性偶尔失败（Empty reply / 超时），拉取最多重试 5 次。
  remote "set -e; cd '$REMOTE_PATH'; echo '--- 更新前提交'; sudo git rev-parse --short HEAD; if [ -n \"\$(sudo git status --porcelain --untracked-files=no)\" ]; then echo '远端工作区有未提交改动，已中止（请先处理后再更新）' >&2; sudo git status --porcelain --untracked-files=no | head >&2; exit 3; fi; ok=0; for attempt in 1 2 3 4 5; do if sudo git pull --ff-only; then ok=1; break; fi; echo \"git pull 失败（第 \$attempt/5 次），10 秒后重试...\" >&2; sleep 10; done; [ \"\$ok\" = 1 ] || { echo 'git pull 连续失败，已中止' >&2; exit 1; }; echo '--- 更新后提交'; sudo git rev-parse --short HEAD"
  if ((BUILD_BACKEND)); then
    log "重建后端镜像（pyproject / uv.lock 变化时依赖才会更新）"
    remote "set -e; cd '$REMOTE_PATH'; sudo docker compose --env-file .env.prod -f docker-compose.prod.yml build backend"
  fi
  remote "set -e; cd '$REMOTE_PATH'; sudo ./deploy.sh update"
fi

# ---------- 前端 ----------
if ((FRONTEND)); then
  log "上传前端构建产物"
  remote_tmp=""
  if ((DRY_RUN)); then
    remote_tmp="/tmp/kiwi-dist.XXXXXX"
  else
    remote_tmp="$(remote_capture 'mktemp -d /tmp/kiwi-dist.XXXXXX')"
    [[ "$remote_tmp" == /tmp/kiwi-dist.* ]] || fail "远端临时目录异常：$remote_tmp"
  fi

  if ((DRY_RUN)); then
    run rsync -az --delete -e "ssh ${SSH_OPTS[*]}" "$DIST/" "$SSH_TARGET:$remote_tmp/"
  else
    rsync -az --delete --info=progress2 -e "ssh ${SSH_OPTS[*]}" "$DIST/" "$SSH_TARGET:$remote_tmp/"
  fi

  log "替换 dist 并重启前端"
  remote "set -e; sudo rsync -a --delete '$remote_tmp/' '$REMOTE_PATH/frontend/dist/'; cd '$REMOTE_PATH'; sudo docker compose --env-file .env.prod -f docker-compose.prod.yml restart frontend; case '$remote_tmp' in /tmp/kiwi-dist.*) rm -rf -- '$remote_tmp' ;; esac"

  if ((DRY_RUN == 0)); then
    built_commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' "$DIST/build-info.json" 2>/dev/null || true)"
    remote_commit="$(remote_capture "python3 -c 'import json; print(json.load(open(\"$REMOTE_PATH/frontend/dist/build-info.json\"))[\"commit\"])'" 2>/dev/null || true)"
    if [[ -n "$built_commit" && "$built_commit" == "$remote_commit" ]]; then
      log "前端版本校验通过：$remote_commit"
    elif [[ -n "$built_commit" && -n "$remote_commit" ]]; then
      warn "前端版本校验不一致：本地 $built_commit / 线上 $remote_commit"
    else
      warn "无法自动校验前端版本，请手动确认线上 build-info.json"
    fi
  fi
fi

log "完成"
