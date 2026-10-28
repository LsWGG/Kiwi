"""OCR 结果清洗与大模型排版整理。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services import ocr_formatter
from app.services.llm_factory import LLMFactory
from app.services.ocr_service import clean_ocr_content
from app.services.parser import ParsedDocument


def test_clean_ocr_content_rejects_brace_noise() -> None:
    assert clean_ocr_content("}" * 4000) == ""
    assert clean_ocr_content("}}}}\n}}}}") == ""
    assert clean_ocr_content("") == ""


def test_clean_ocr_content_strips_grounding_and_json() -> None:
    grounded = (
        "<|ref|>text<|/ref|><|det|>[[32, 180, 140, 222]]<|/det|>\n"
        "Kiwi OCR Test\n\n"
        "<|ref|>text<|/ref|><|det|>[[32, 416, 156, 458]]<|/det|>\n"
        "Hello world"
    )
    assert clean_ocr_content(grounded) == "Kiwi OCR Test\n\nHello world"

    fenced = '```json\n{"pages": ["第一页", "第二页"]}\n```'
    assert clean_ocr_content(fenced) == "第一页\n\n第二页"

    wrapped = '{"text": "标题\\n\\n正文"}'
    assert clean_ocr_content(wrapped) == "标题\n\n正文"


def test_llm_factory_normalizes_v1_suffix(monkeypatch) -> None:
    seen: list[str] = []

    def fake_openai(**kwargs):
        seen.append(kwargs["base_url"])
        return SimpleNamespace()

    monkeypatch.setattr("openai.AsyncOpenAI", fake_openai)
    factory = LLMFactory()
    first = factory.get_client("https://api.example.com/v1", "key")
    second = factory.get_client("https://api.example.com/", "key")
    assert first is second
    assert seen == ["https://api.example.com/v1"]


def _fake_client(outputs: list[str]) -> SimpleNamespace:
    calls: list[list[dict]] = []

    async def create(**kwargs):
        calls.append(kwargs["messages"])
        index = len(calls) - 1
        output = outputs[index] if index < len(outputs) else outputs[-1]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=output),
                )
            ]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.calls = calls  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_format_ocr_document_keeps_original_when_no_llm(monkeypatch) -> None:
    async def no_config(_kb_id):
        return None, ""

    monkeypatch.setattr(ocr_formatter, "_resolve_llm_config", no_config)
    parsed = ParsedDocument(
        title="scan",
        text="原样文字",
        parse_engine="online-ocr:test-model",
        quality_report={"ocr": True},
    )
    result = await ocr_formatter.format_ocr_document(parsed, uuid.uuid4())
    assert result.text == "原样文字"
    assert result.quality_report["llm_format"]["enabled"] is False
    assert any("未配置大模型" in item for item in result.warnings)


@pytest.mark.asyncio
async def test_format_ocr_document_uses_llm_and_preserves_text(monkeypatch) -> None:
    cfg = SimpleNamespace(base_url="http://127.0.0.1:11434", model_name="test-model")
    fake_client = _fake_client(["# 标题\n\n整理后的正文"])

    async def config(_kb_id):
        return cfg, "key"

    monkeypatch.setattr(ocr_formatter, "_resolve_llm_config", config)
    monkeypatch.setattr(
        ocr_formatter.LLMFactory,
        "get_client",
        lambda self, base_url, api_key=None, model="": fake_client,
    )
    parsed = ParsedDocument(
        title="scan",
        text="标题\n\n正文",
        parse_engine="online-ocr:test-model",
        quality_report={},
    )
    result = await ocr_formatter.format_ocr_document(parsed, uuid.uuid4())
    assert result.text == "# 标题\n\n整理后的正文"
    assert result.quality_report["llm_format"]["enabled"] is True
    assert result.quality_report["llm_format"]["failed_chunks"] == 0
    assert fake_client.calls[0][0]["role"] == "system"
    prompt = fake_client.calls[0][0]["content"]
    assert "不得翻译" in prompt
    assert "页眉" in prompt and "页脚" in prompt


@pytest.mark.asyncio
async def test_format_ocr_document_restores_dropped_images(monkeypatch) -> None:
    cfg = SimpleNamespace(base_url="http://127.0.0.1:11434", model_name="test-model")
    fake_client = _fake_client(["整理后的正文"])

    async def config(_kb_id):
        return cfg, "key"

    image = "![第 1 页图 1](/media/kb/ocr-abc.png)"
    monkeypatch.setattr(ocr_formatter, "_resolve_llm_config", config)
    monkeypatch.setattr(
        ocr_formatter.LLMFactory,
        "get_client",
        lambda self, base_url, api_key=None, model="": fake_client,
    )
    parsed = ParsedDocument(
        title="scan",
        text=f"正文\n\n{image}",
        parse_engine="online-ocr:test-model",
        quality_report={},
    )
    result = await ocr_formatter.format_ocr_document(parsed, uuid.uuid4())

    assert image in result.text
    assert any("补回" in item for item in result.warnings)


@pytest.mark.asyncio
async def test_format_ocr_document_falls_back_on_llm_failure(monkeypatch) -> None:
    cfg = SimpleNamespace(base_url="http://127.0.0.1:11434", model_name="test-model")

    async def config(_kb_id):
        return cfg, "key"

    async def boom(**_kwargs):
        raise RuntimeError("provider down")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=boom))
    )
    monkeypatch.setattr(ocr_formatter, "_resolve_llm_config", config)
    monkeypatch.setattr(
        ocr_formatter.LLMFactory,
        "get_client",
        lambda self, base_url, api_key=None, model="": fake_client,
    )

    parsed = ParsedDocument(
        title="scan",
        text="原文",
        parse_engine="tesseract-ocr",
        quality_report={},
    )
    result = await ocr_formatter.format_ocr_document(parsed, uuid.uuid4())
    assert result.text == "原文"
    assert result.quality_report["llm_format"]["failed_chunks"] == 1
    assert any("失败" in item for item in result.warnings)
