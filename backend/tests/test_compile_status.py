"""编译任务状态对齐：悬空 / 终态业务任务不应长期停在「排队中」。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import IngestJob, Job, Source
from app.services.compile_status import reconcile_ingest_jobs


async def _make_source(db, kb_id: uuid.UUID) -> Source:
    source = Source(
        kb_id=kb_id,
        type="note",
        title="编译状态测试",
        raw_path=f"data/uploads/{kb_id}/test.md",
        sha256="0" * 64,
        status="parsed",
    )
    db.add(source)
    await db.flush()
    return source


async def _make_ingest(
    db,
    kb_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    status: str = "pending",
    created_at: datetime | None = None,
) -> IngestJob:
    row = IngestJob(
        kb_id=kb_id,
        source_id=source_id,
        kind="compile",
        status=status,
        progress=0.0,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


async def test_stale_pending_without_durable_job_fails(db, kb):
    kb_id = uuid.UUID(kb["id"])
    source = await _make_source(db, kb_id)
    row = await _make_ingest(
        db,
        kb_id,
        source.id,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    changed = await reconcile_ingest_jobs(db, kb_id, grace_seconds=120)
    await db.commit()
    await db.refresh(row)
    assert changed == 1
    assert row.status == "failed"
    assert "未找到对应的后台任务" in (row.error or "")


async def test_recent_pending_without_durable_job_waits_for_grace(db, kb):
    kb_id = uuid.UUID(kb["id"])
    source = await _make_source(db, kb_id)
    row = await _make_ingest(db, kb_id, source.id)
    changed = await reconcile_ingest_jobs(db, kb_id, grace_seconds=120)
    await db.commit()
    await db.refresh(row)
    assert changed == 0
    assert row.status == "pending"


async def test_failed_durable_job_propagates_error(db, kb):
    kb_id = uuid.UUID(kb["id"])
    source = await _make_source(db, kb_id)
    row = await _make_ingest(db, kb_id, source.id)
    job = Job(
        kind="note_compile",
        status="failed",
        payload={"ingest_job_id": str(row.id)},
        result={},
        kb_id=kb_id,
        ref_id=str(row.id),
        idempotency_key=f"compile:{row.id}",
        error="大模型调用超时",
    )
    db.add(job)
    await db.flush()

    changed = await reconcile_ingest_jobs(db, kb_id)
    await db.commit()
    await db.refresh(row)
    assert changed == 1
    assert row.status == "failed"
    assert row.error == "大模型调用超时"


async def test_success_closes_pending_row(db, kb):
    """任务很快成功时，业务记录可能还停在 pending，也要对齐为成功。"""
    kb_id = uuid.UUID(kb["id"])
    source = await _make_source(db, kb_id)
    row = await _make_ingest(db, kb_id, source.id, status="pending")
    job = Job(
        kind="note_compile",
        status="succeeded",
        payload={"ingest_job_id": str(row.id)},
        result={"touched_page_ids": []},
        kb_id=kb_id,
        ref_id=str(row.id),
        idempotency_key=f"compile:{row.id}",
    )
    db.add(job)
    await db.flush()

    await reconcile_ingest_jobs(db, kb_id)
    await db.commit()
    await db.refresh(row)
    assert row.status == "succeeded"
    assert row.progress == 1.0


@pytest.mark.parametrize("job_status", ["succeeded", "cancelled"])
async def test_terminal_durable_job_closes_running_row(db, kb, job_status):
    kb_id = uuid.UUID(kb["id"])
    source = await _make_source(db, kb_id)
    row = await _make_ingest(db, kb_id, source.id, status="running")
    job = Job(
        kind="note_compile",
        status=job_status,
        payload={"ingest_job_id": str(row.id)},
        result={"touched_page_ids": ["page-1"]},
        kb_id=kb_id,
        ref_id=str(row.id),
        idempotency_key=f"compile:{row.id}",
    )
    db.add(job)
    await db.flush()

    await reconcile_ingest_jobs(db, kb_id)
    await db.commit()
    await db.refresh(row)
    if job_status == "succeeded":
        assert row.status == "succeeded"
        assert row.progress == 1.0
        assert row.touched_page_ids == ["page-1"]
    else:
        assert row.status == "failed"
        assert row.error == "任务已取消"
