.PHONY: dev stop logs migrate reset rebuild prune kbs ps health qdrant-models

# 一键启动（幂等）
dev:
	./run.sh

# 停止基础设施容器（保留数据卷）
stop:
	docker compose stop

# 查看基础设施日志
logs:
	docker compose logs -f

# 执行数据库迁移
migrate:
	cd backend && uv run alembic upgrade head

# 重置数据库（清空数据卷！）
reset:
	docker compose down -v
	rm -rf backend/.venv frontend/node_modules

# 重新构建基础设施容器
rebuild:
	docker compose up -d --force-recreate

# 进程状态
ps:
	docker compose ps

# 后端测试
test-backend:
	cd backend && uv run pytest -q

# 类型检查前端
typecheck-frontend:
	cd frontend && npm run type-check

# 清理未使用容器/镜像
prune:
	docker system prune -f