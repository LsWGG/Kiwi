"""PDF 逐页 OCR 容错回归：单页失败不应丢弃整份识别结果。"""

from __future__ import annotations

import fitz
import pytest

from app.services import ocr_service


def _make_pdf(path, pages: int = 3) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {index + 1}")
    doc.save(str(path))
    doc.close()


def test_ocr_pdf_pages_skips_failed_page(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf)
    calls: list[int] = []

    def fake_ocr(image, config=None, mime=None):
        calls.append(1)
        if len(calls) == 2:
            raise ocr_service.OcrError("模拟超时")
        return f"text-{len(calls)}"

    monkeypatch.setattr(ocr_service, "ocr_image_bytes", fake_ocr)
    text, warnings = ocr_service.ocr_pdf_pages(pdf)

    assert "text-1" in text
    assert "text-3" in text
    assert "text-2" not in text
    assert any("第 2 页" in item for item in warnings)


def test_ocr_pdf_pages_raises_when_all_pages_fail(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, pages=2)

    def fake_ocr(image, config=None, mime=None):
        raise ocr_service.OcrError("模拟失败")

    monkeypatch.setattr(ocr_service, "ocr_image_bytes", fake_ocr)

    with pytest.raises(ocr_service.OcrError):
        ocr_service.ocr_pdf_pages(pdf)
