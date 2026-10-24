# syntax=docker/dockerfile:1.7
# Kiwi 后端镜像：FastAPI + 迁移 + bubblewrap Notebook 沙箱。
# 构建上下文为仓库根目录：docker build -f deploy/backend.Dockerfile .
#
# 国内网络默认使用清华镜像下载 PyPI 与 Debian 依赖，构建时可通过
# --build-arg PYPI_INDEX_URL=... / DEBIAN_MIRROR=... 覆盖。

FROM python:3.12-slim-bookworm AS builder

ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    PIP_INDEX_URL=${PYPI_INDEX_URL}

# uv 通过 PyPI 镜像安装，避免额外从 ghcr.io 拉取镜像。
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install "uv==0.12.13"

# 切换 Debian 软件源（兼容 sources.list 与 deb822 的 debian.sources）。
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
      [ -f "$f" ] || continue; \
      sed -i \
        -e "s|http[s]*://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http[s]*://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http[s]*://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        "$f"; \
    done; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev

WORKDIR /app

# 先只装第三方依赖，源码变化时复用依赖层。
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3.12

COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --python /usr/local/bin/python3.12


FROM python:3.12-slim-bookworm AS runtime

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
# 备份使用 pg_dump，客户端必须与服务端同大版本（Compose 固定 postgres:16）。
# Debian bookworm 自带的是 PostgreSQL 15 客户端，因此从 PGDG 安装 16。
ARG PGDG_MIRROR=https://mirrors.aliyun.com/postgresql/repos/apt
ARG KIWI_BUILD_COMMIT=""
ARG KIWI_BUILD_TIME=""

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    KIWI_BUILD_COMMIT=${KIWI_BUILD_COMMIT} \
    KIWI_BUILD_TIME=${KIWI_BUILD_TIME} \
    PATH="/app/.venv/bin:$PATH"

# bubblewrap / prlimit 是 Notebook 沙箱的运行时依赖；字体用于图表中文渲染。
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
      [ -f "$f" ] || continue; \
      sed -i \
        -e "s|http[s]*://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http[s]*://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http[s]*://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        "$f"; \
    done; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL "${PGDG_MIRROR}/ACCC4CF8.asc" \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] ${PGDG_MIRROR} bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      bubblewrap \
      util-linux \
      postgresql-client-16 \
      libgomp1 \
      libglib2.0-0 \
      libgl1 \
      libxml2 \
      libxslt1.1 \
      fonts-noto-cjk \
      media-types; \
    pg_dump --version; \
    pg_dump --version | grep -q ' 16\.'

# 保留 uv / uvx：Notebook 的 %uv / uv pip 与独立虚拟环境需要它。
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /usr/local/bin/uvx /usr/local/bin/uvx
COPY --from=builder /app /app

COPY deploy/entrypoint.sh /usr/local/bin/kiwi-entrypoint
RUN chmod +x /usr/local/bin/kiwi-entrypoint \
  && mkdir -p /app/data/uploads /app/data/notebooks /app/data/wiki_schemas

WORKDIR /app
EXPOSE 8000

# 数据目录（上传、Notebook 工作区、Wiki Schema、嵌入模型缓存）由 compose 挂载。
VOLUME ["/app/data"]

ENTRYPOINT ["kiwi-entrypoint"]
