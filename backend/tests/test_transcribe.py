"""语音转写：上传入队、任务生成会议笔记、飞书妙记授权与 Markdown 排版。"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app.config import settings
from app.db.models import Job, Note
from app.db.session import async_session_factory
from app.services import feishu_minutes, job_handlers, transcription


def _provider(choice: str) -> tuple[str, feishu_minutes.FeishuConfig]:
    return choice, feishu_minutes.FeishuConfig(provider=choice)


def _result() -> dict:
    return {
        "text": "大家好，今天讨论缓存设计。\n先确认命中率目标。",
        "segments": [
            {"start": 0.0, "end": 3.2, "text": "大家好，今天讨论缓存设计。"},
            {"start": 3.2, "end": 8.5, "text": "先确认命中率目标。"},
        ],
        "language": "zh",
        "language_probability": 0.98,
        "duration": 8.5,
    }


async def test_transcribe_upload_queues_job(client, kb):
    resp = await client.post(
        f"/api/transcribe?kb_id={kb['id']}",
        files={"file": ("meeting.mp3", b"fake-audio-bytes", "audio/mpeg")},
        data={"language": "zh", "title": "周会", "summarize": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    job_id = uuid.UUID(body["job_id"])

    async with async_session_factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.kind == "transcribe"
        assert job.status == "pending"
        assert job.max_attempts == 1
        assert job.payload["language"] == "zh"
        assert job.payload["title"] == "周会"
        path = Path(job.payload["path"])
        assert path.exists()
        path.unlink(missing_ok=True)
        await session.delete(job)
        await session.commit()


async def test_transcribe_job_creates_meeting_note(kb, monkeypatch):
    async def fake_transcribe(
        path: Path,
        *,
        language: str = "auto",
        provider: str | None = None,
        original_name: str = "",
    ) -> dict:
        assert path.exists()
        assert original_name == "产品评审.mp3"
        return _result()

    async def fake_summary(text: str, kb_id: uuid.UUID) -> str:
        assert "缓存设计" in text
        return "## 摘要\n\n确认缓存命中率目标。"

    monkeypatch.setattr(transcription, "transcribe_file", fake_transcribe)
    monkeypatch.setattr(transcription, "summarize_transcript", fake_summary)

    audio_dir = settings.upload_dir / "transcribe"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{uuid.uuid4().hex}.mp3"
    path.write_bytes(b"fake-audio")

    payload = {
        "path": str(path),
        "kb_id": kb["id"],
        "language": "zh",
        "title": "",
        "filename": "产品评审.mp3",
        "summarize": True,
        "create_note": True,
    }
    result = await job_handlers.run_transcribe_job(SimpleNamespace(id=uuid.uuid4()), payload)

    assert result["note_id"]
    assert result["summarized"] is True
    assert result["duration"] == 8.5
    assert result["provider"] == "local"
    assert not path.exists()

    async with async_session_factory() as session:
        notes = (
            (
                await session.execute(
                    select(Note).where(
                        Note.kb_id == uuid.UUID(kb["id"]),
                        Note.kind == "doc",
                    )
                )
            )
            .scalars()
            .all()
        )
        note = next(item for item in notes if item.title == "产品评审")
        assert "会议摘要" in note.body_md
        assert "确认缓存命中率目标" in note.body_md
        assert "**00:00**" in note.body_md
        assert "**00:03**" in note.body_md
        assert note.props_json["source"] == "transcription"
        assert note.props_json["audio"]["language"] == "zh"


def test_render_markdown_without_segments():
    markdown = transcription.render_markdown(
        {"text": "纯文本转写", "segments": [], "duration": 65, "language": "en"},
        original_name="standup.wav",
    )
    assert "standup.wav" in markdown
    assert "01:05" in markdown
    assert "英语" in markdown
    assert "纯文本转写" in markdown


def test_render_markdown_feishu_meta_and_fallback():
    markdown = transcription.render_markdown(
        {
            "text": "逐字稿",
            "segments": [{"start": 0, "end": 2, "text": "逐字稿"}],
            "duration": 2,
            "language": "",
            "provider": "feishu",
            "minute_url": "https://www.feishu.cn/minutes/obcn123",
        },
        original_name="周会.webm",
    )
    assert "飞书妙记" in markdown
    assert "妙记链接：https://www.feishu.cn/minutes/obcn123" in markdown

    fallback = transcription.render_markdown(
        {
            "text": "回退文本",
            "segments": [],
            "duration": 1,
            "language": "zh",
            "provider": "local",
            "fallback_reason": "飞书接口超时",
        },
        original_name="周会.webm",
    )
    assert "回退本地转写" in fallback
    assert "飞书接口超时" in fallback


def test_parse_srt_segments():
    content = (
        "1\n00:00:01,000 --> 00:00:03,000\n大家好\n\n"
        "2\n00:00:03,000 --> 00:00:05,500\n今天讨论缓存\n第二行\n\n"
        "1\n00:00:01,000 --> 00:00:03,000\n大家好\n"
    )
    segments = feishu_minutes.parse_srt(content)
    assert [item["start"] for item in segments] == [1.0, 3.0]
    assert segments[1]["text"] == "今天讨论缓存 第二行"
    assert segments[1]["end"] == 5.5


def test_build_authorize_url_contains_scope():
    url = feishu_minutes.build_authorize_url(
        "cli_app", "http://localhost:5173/api/transcribe/feishu/oauth/callback", "state-1"
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.netloc == "accounts.feishu.cn"
    assert query["client_id"] == ["cli_app"]
    assert query["state"] == ["state-1"]
    assert "offline_access" in query["scope"][0]
    assert "minutes:minutes.transcript:export" in query["scope"][0]


async def _configure_feishu(client) -> None:
    resp = await client.put(
        "/api/settings/system",
        json={
            "transcribe_provider": "feishu",
            "feishu_app_id": "cli_pytest",
            "feishu_app_secret": "secret_pytest",
            "feishu_redirect_uri": "",
        },
    )
    assert resp.status_code == 200, resp.text


async def _reset_feishu(client) -> None:
    await client.put(
        "/api/settings/system",
        json={
            "transcribe_provider": "auto",
            "feishu_app_id": "",
            "feishu_app_secret": "",
            "feishu_user_token": "",
            "feishu_refresh_token": "",
            "feishu_folder_token": "",
            "feishu_redirect_uri": "",
        },
    )


async def test_feishu_oauth_start_and_status(client):
    await _configure_feishu(client)
    try:
        resp = await client.post(
            "/api/transcribe/feishu/oauth/start",
            json={"origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["redirect_uri"].endswith("/api/transcribe/feishu/oauth/callback")
        assert body["redirect_uri"].startswith("http://localhost:5173")
        assert "accounts.feishu.cn" in body["authorize_url"]

        status = await client.get(
            f"/api/transcribe/feishu/oauth/status?state={body['state']}"
        )
        assert status.json()["status"] == "pending"

        unknown = await client.get("/api/transcribe/feishu/oauth/status?state=missing")
        assert unknown.json()["status"] == "expired"

        # 未授权前通道状态应提示飞书尚未就绪
        state = await client.get("/api/transcribe/status")
        payload = state.json()
        assert payload["provider"] == "feishu"
        assert payload["provider_ready"] is False
    finally:
        await _reset_feishu(client)


async def test_feishu_oauth_start_requires_credentials(client):
    await _reset_feishu(client)
    resp = await client.post(
        "/api/transcribe/feishu/oauth/start", json={"origin": "http://localhost:5173"}
    )
    assert resp.status_code == 400
    assert "App ID" in resp.json()["detail"]


async def test_feishu_oauth_callback_rejects_unknown_state(client):
    resp = await client.get(
        "/api/transcribe/feishu/oauth/callback?code=abc&state=missing"
    )
    assert resp.status_code == 200
    assert "授权会话无效" in resp.text


async def test_transcribe_preview_shifts_offsets(client, monkeypatch):
    async def fake_preview(path: Path, *, language: str = "auto") -> dict:
        assert path.exists()
        return {
            "text": "片段",
            "segments": [{"start": 0.5, "end": 2.0, "text": "片段"}],
            "language": language,
            "duration": 2.0,
        }

    monkeypatch.setattr(transcription, "transcribe_preview", fake_preview)
    resp = await client.post(
        "/api/transcribe/preview",
        files={"file": ("chunk.webm", b"fake-chunk", "audio/webm")},
        data={"language": "zh", "offset": "10"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["segments"][0]["start"] == 10.5
    assert body["segments"][0]["end"] == 12.0
    assert body["offset"] == 10


async def test_transcribe_preview_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "whisper_enabled", False)
    resp = await client.post(
        "/api/transcribe/preview",
        files={"file": ("chunk.webm", b"fake", "audio/webm")},
    )
    assert resp.status_code == 400
    assert "实时预览" in resp.json()["detail"]


async def test_feishu_test_endpoint_uses_saved_config(client, monkeypatch):
    async def fake_test(config):
        return True, f"ok:{config.app_id}"

    monkeypatch.setattr(feishu_minutes, "test_connection", fake_test)
    await _configure_feishu(client)
    try:
        resp = await client.post("/api/transcribe/feishu/test")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "message": "ok:cli_pytest"}
    finally:
        await _reset_feishu(client)


async def test_transcribe_provider_fallback_to_local(monkeypatch):
    async def failing_feishu(path, *, original_name="", config=None):
        raise feishu_minutes.FeishuError("飞书接口不可用")

    async def fake_local(path, language, *, fast=False):
        return {
            "text": "本地兜底",
            "segments": [],
            "language": language,
            "duration": 1,
            "provider": "local",
        }

    async def fake_resolve(preference=None):
        return _provider("feishu")

    monkeypatch.setattr(feishu_minutes, "transcribe_audio", failing_feishu)
    monkeypatch.setattr(transcription, "_local_transcribe", fake_local)
    monkeypatch.setattr(transcription, "resolve_provider", fake_resolve)
    result = await transcription.transcribe_file(Path("audio.webm"), provider="auto")
    assert result["provider"] == "local"
    assert "飞书接口不可用" in result["fallback_reason"]

    try:
        await transcription.transcribe_file(Path("audio.webm"), provider="feishu")
    except transcription.TranscriptionError as exc:
        assert "飞书接口不可用" in str(exc)
    else:
        raise AssertionError("强制飞书时应抛出 TranscriptionError")


async def test_transcribe_feishu_failure_without_local(monkeypatch):
    async def failing_feishu(path, *, original_name="", config=None):
        raise feishu_minutes.FeishuError("飞书接口不可用")

    async def fake_resolve(preference=None):
        return _provider("feishu")

    monkeypatch.setattr(feishu_minutes, "transcribe_audio", failing_feishu)
    monkeypatch.setattr(transcription, "resolve_provider", fake_resolve)
    monkeypatch.setattr(settings, "whisper_enabled", False)
    try:
        await transcription.transcribe_file(Path("audio.webm"), provider="auto")
    except transcription.TranscriptionError as exc:
        assert "飞书接口不可用" in str(exc)
    else:
        raise AssertionError("本地转写关闭时不应回退")


async def test_transcription_status_local(client, monkeypatch):
    async def no_config():
        return feishu_minutes.FeishuConfig()

    monkeypatch.setattr(feishu_minutes, "load_config", no_config)
    resp = await client.get("/api/transcribe/status")
    body = resp.json()
    assert body["provider"] == "local"
    assert body["local"]["model"] == settings.whisper_model
    assert body["preview_enabled"] is True
