"""无向量模型（桌面版 ``provider=none``）行为测试。

桌面版不内置 embedding 模型：解析、笔记正文与 PostgreSQL 全文检索仍可用，
语义检索 / 问答等依赖向量的接口返回明确状态，而不是在后台尝试加载模型。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import IngestJob, Job, Note, Source
from app.db.session import async_session_factory
from app.services import embedding_settings, ingest_service, qdrant_store
from app.services.embedder import (
    EmbeddingRuntimeConfig,
    EmbeddingUnavailable,
    configure_runtime,
    embed_texts_async,
    embedding_space,
    is_disabled,
)
from app.services.note_indexer import ensure_notes_indexed


@pytest.fixture
def vectors_disabled():
    """模拟桌面运行时注入的 provider=none。"""
    configure_runtime(
        EmbeddingRuntimeConfig(
            provider="none",
            api_base="",
            api_key="",
            api_model="",
            timeout=60.0,
            batch_size=64,
            concurrency=4,
        )
    )
    try:
        yield
    finally:
        configure_runtime(None)


def test_none_provider_disables_vectors(vectors_disabled):
    assert is_disabled()
    assert embedding_settings.normalize_provider("none") == "none"
    assert embedding_settings.normalize_provider("NONE") == "none"
    assert embedding_settings.is_disabled("none")
    assert embedding_settings.space_for("none", "") == "disabled"
    assert embedding_space("BAAI/bge-small-zh-v1.5") == "disabled"


def test_other_providers_stay_enabled():
    # 默认（无 override）仍按环境变量走，不受 none 分支影响。
    assert embedding_settings.normalize_provider("local") == "local"
    assert embedding_settings.normalize_provider("openai") == "openai"
    assert embedding_settings.space_for("local", "") != "disabled"


async def test_embed_texts_raises_when_disabled(vectors_disabled):
    with pytest.raises(EmbeddingUnavailable):
        await embed_texts_async(["索引"])
    # 空输入不触发模型加载，保持原语义。
    assert await embed_texts_async([]) == []


async def test_note_indexer_skips_work(vectors_disabled):
    stats = await ensure_notes_indexed([uuid.uuid4()], force=True)
    assert stats == {
        "indexed": 0,
        "skipped": 0,
        "deleted": 0,
        "failed": 0,
        "vectors_disabled": True,
    }


async def test_search_endpoint_returns_409(client, kb, vectors_disabled):
    resp = await client.post(
        "/api/search",
        json={"query": "索引", "scope": {"scope": "kb", "kb_ids": [kb["id"]]}},
    )
    assert resp.status_code == 409, resp.text
    assert "向量模型已关闭" in resp.json()["detail"]


async def test_chat_endpoint_returns_409(client, kb, vectors_disabled):
    resp = await client.post(
        "/api/chat/stream",
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "scope": {"scope": "kb", "kb_ids": [kb["id"]]},
        },
    )
    assert resp.status_code == 409, resp.text
    assert "向量模型已关闭" in resp.json()["detail"]


async def test_reindex_endpoints_return_409(client, kb, vectors_disabled):
    notes = await client.post(f"/api/notes/reindex?kb_id={kb['id']}")
    assert notes.status_code == 409, notes.text
    wiki = await client.post(f"/api/wiki/reindex?kb_id={kb['id']}")
    assert wiki.status_code == 409, wiki.text


async def test_note_search_remains_available(client, kb, note_factory, vectors_disabled):
    note = await note_factory(title="离线关键字笔记")
    resp = await client.get(f"/api/notes/search?kb_id={kb['id']}&q=离线关键字")
    assert resp.status_code == 200, resp.text
    ids = [item["note"]["id"] for item in resp.json()["items"]]
    assert note["id"] in ids


async def test_ingest_keeps_note_body_without_vectors(
    client, db, kb, note_factory, tmp_path, vectors_disabled, monkeypatch
):
    """导入仍完成解析与笔记正文写入，只是不写向量。"""
    note = await note_factory(title="待导入笔记")
    raw = tmp_path / "offline.md"
    raw.write_text("# 离线导入\n\n正文保留在笔记中。", encoding="utf-8")
    kb_id = uuid.UUID(kb["id"])
    source = Source(
        kb_id=kb_id,
        type="md",
        title="离线导入",
        raw_path=str(raw),
        sha256="0" * 64,
        status="received",
    )
    db.add(source)
    await db.flush()
    job = IngestJob(
        kb_id=kb_id,
        source_id=source.id,
        kind="ingest",
        status="pending",
        note_id=uuid.UUID(note["id"]),
    )
    db.add(job)
    await db.commit()
    job_id = job.id
    source_id = source.id
    note_id = uuid.UUID(note["id"])

    calls: list[str] = []
    monkeypatch.setattr(
        ingest_service.qdrant_store,
        "delete_source_chunks",
        lambda *args, **kwargs: calls.append("delete"),
    )
    monkeypatch.setattr(
        ingest_service.qdrant_store,
        "upsert_chunks",
        lambda *args, **kwargs: calls.append("upsert"),
    )

    await ingest_service._process_ingest(
        str(job_id),
        kb_id,
        source_id,
        compile_now=False,
        note_id=note_id,
        embed_raw=True,
    )

    async with async_session_factory() as fresh:
        stored_job = await fresh.get(IngestJob, job_id)
        stored_note = await fresh.get(Note, note_id)
        assert stored_job is not None and stored_job.status == "succeeded"
        assert stored_note is not None
        assert "正文保留在笔记中" in (stored_note.body_md or "")
    assert calls == []


async def test_wiki_compile_related_pages_skip_retrieval(db, kb, vectors_disabled):
    from app.db.models import KnowledgeBase
    from app.services.wiki_compiler import _related_wiki_pages

    kb_row = await db.get(KnowledgeBase, uuid.UUID(kb["id"]))
    assert kb_row is not None
    pages = await _related_wiki_pages(db, kb_row, [{"content": "索引优化"}])
    assert pages == []


async def test_wiki_page_create_skips_vector_writes(
    client, kb, vectors_disabled, monkeypatch
):
    calls: list[tuple] = []
    monkeypatch.setattr(
        qdrant_store, "upsert_wiki_pages", lambda *args, **kwargs: calls.append(args)
    )
    resp = await client.post(
        f"/api/wiki?kb_id={kb['id']}",
        json={"title": "离线页面", "page_type": "concept", "body_md": "正文内容"},
    )
    assert resp.status_code == 201, resp.text
    assert calls == []


async def test_settings_accept_none_provider(client, vectors_disabled):
    # 先清掉测试库里可能残留的配置，保证从环境变量默认状态开始。
    await client.delete("/api/settings/embedding")

    resp = await client.put(
        "/api/settings/embedding",
        json={"provider": "none", "api_base": "", "api_model": ""},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider"] == "none"
    assert data["active_space"] == "disabled"

    test = await client.post("/api/settings/embedding/test", json={"provider": "none"})
    assert test.status_code == 200, test.text
    assert test.json()["ok"] is True

    # 清理配置，避免影响其它测试对默认 provider 的假设。
    await client.delete("/api/settings/embedding")


async def test_health_reports_disabled_instead_of_degraded(
    client, db, vectors_disabled, monkeypatch
):
    probed: list[bool] = []

    def _probe(*args, **kwargs):
        probed.append(True)
        raise AssertionError("provider=none 时不应探测 Qdrant")

    monkeypatch.setattr(qdrant_store, "count_raw_points", _probe)
    resp = await client.get("/api/health/detail")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["qdrant"] == "disabled"
    assert data["embedding"] == {"enabled": False, "provider": "none"}
    assert probed == []

    failed = (
        await db.execute(select(func.count(Job.id)).where(Job.status == "failed"))
    ).scalar_one()
    if failed == 0:
        assert data["status"] == "ok"
