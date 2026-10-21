"""测试环境配置。

测试必须连接独立的 PostgreSQL 库；通过 ``KIWI_TEST_DATABASE_URL`` 显式提供，
避免误用仓库根目录 ``.env`` 中指向线上实例的 ``KIWI_DATABASE_URL``。
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

# 必须在导入 app.* 之前设置，settings 在首次导入时读取环境变量。
TEST_DATABASE_URL = os.environ.get("KIWI_TEST_DATABASE_URL", "").strip()
if not TEST_DATABASE_URL:
    pytest.exit(
        "请设置 KIWI_TEST_DATABASE_URL（独立测试库），例如：\n"
        "  KIWI_TEST_DATABASE_URL=postgresql+asyncpg://kiwi:kiwi@localhost:5432/kiwi_test "
        "uv run pytest",
        returncode=2,
    )
if TEST_DATABASE_URL.rstrip("/").endswith("/kiwi"):
    pytest.exit("拒绝在线上库 kiwi 上运行测试，请使用独立的测试数据库。", returncode=2)

os.environ["KIWI_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["KIWI_BACKGROUND_JOBS"] = "false"
os.environ["KIWI_ACCESS_TOKEN"] = ""
# 测试使用固定密钥，避免把真实 KIWI_FERNET_KEY 用于测试数据。
os.environ["KIWI_FERNET_KEY"] = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
os.environ.setdefault("KIWI_QDRANT_URL", "http://localhost:6333")


@pytest.fixture(scope="session", autouse=True)
def _migrate_database() -> None:
    """用 Alembic 建出与生产一致的 schema（同时验证迁移可执行）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "KIWI_DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.exit(
            "测试库迁移失败，请确认 KIWI_TEST_DATABASE_URL 可连接：\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}",
            returncode=2,
        )


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def db():
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        yield session


@pytest.fixture
async def kb(client):
    """创建一个隔离知识库，测试结束后删除。"""
    name = f"pytest-{uuid.uuid4().hex[:10]}"
    resp = await client.post("/api/kbs", json={"name": name})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/kbs/{data['id']}")


@pytest.fixture
async def note_factory(client, kb):
    created: list[str] = []

    async def create(**kwargs) -> dict:
        payload = {"title": f"note-{uuid.uuid4().hex[:8]}", "kind": "doc"}
        payload.update(kwargs)
        resp = await client.post(f"/api/notes?kb_id={kb['id']}", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        created.append(data["id"])
        return data

    yield create
