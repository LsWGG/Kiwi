# syntax=docker/dockerfile:1.7
# Kiwi 后端镜像：FastAPI + 迁移 + bubblewrap Notebook 沙箱。
# 构建上下文为仓库根目录：docker build -f deploy/backend.Dockerfile .

FROM python:3.12-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只装第三方依赖，源码变化时复用依赖层。
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3.12

COPY backend/ ./
RUN uv sync --frozen --no-dev --python /usr/local/bin/python3.12


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# bubblewrap / prlimit 是 Notebook 沙箱的运行时依赖；字体用于图表中文渲染。
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    bubblewrap \
    util-linux \
    curl \
    ca-certificates \
    libgomp1 \
    libglib2.0-0 \
    libgl1 \
    libxml2 \
    libxslt1.1 \
    fonts-noto-cjk \
    media-types \
  && rm -rf /var/lib/apt/lists/*

# 保留 uv：Notebook 的 %uv / uv pip 与独立虚拟环境需要它。
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv
COPY --from=builder /app /app

COPY deploy/entrypoint.sh /usr/local/bin/kiwi-entrypoint
RUN chmod +x /usr/local/bin/kiwi-entrypoint \
  && mkdir -p /app/data/uploads /app/data/notebooks /app/data/wiki_schemas

WORKDIR /app
EXPOSE 8000

# 数据目录（上传、Notebook 工作区、Wiki Schema、嵌入模型缓存）由 compose 挂载。
VOLUME ["/app/data"]

ENTRYPOINT ["kiwi-entrypoint"]
