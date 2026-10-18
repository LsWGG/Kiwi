# syntax=docker/dockerfile:1.7
# Kiwi 前端镜像：Vite 构建 + nginx 静态托管与 API 反向代理。
# 构建上下文为仓库根目录：docker build -f deploy/frontend.Dockerfile .

FROM node:22-alpine AS build

# 国内网络默认使用 npmmirror；海外或私有镜像可在 .env.prod / build-arg 中覆盖。
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /app
ENV NODE_OPTIONS=--max-old-space-size=4096

COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry "$NPM_REGISTRY" \
    && npm ci --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=20000

COPY frontend/ ./
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
