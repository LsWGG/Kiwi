# syntax=docker/dockerfile:1.7
# Kiwi 前端运行时镜像（可选）：只打包宿主机预构建的 dist，不在镜像构建期安装 npm
# 依赖或执行 Vite，避免低内存主机在 docker build 时 OOM。
#
# 生产 Compose 默认不构建此镜像，而是把 ./frontend/dist 直接只读挂载到 nginx。
# 需要不可变镜像时：
#   (cd frontend && npm ci && npm run build)
#   docker build -f deploy/frontend.Dockerfile -t kiwi-frontend .

FROM nginx:1.27-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/dist /usr/share/nginx/html

EXPOSE 80
