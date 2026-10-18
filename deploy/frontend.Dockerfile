# syntax=docker/dockerfile:1.7
# Kiwi 前端镜像：Vite 构建 + nginx 静态托管与 API 反向代理。
# 构建上下文为仓库根目录：docker build -f deploy/frontend.Dockerfile .

FROM node:22-alpine AS build

WORKDIR /app
ENV NODE_OPTIONS=--max-old-space-size=4096

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
