"""PDF 逐页 OCR 容错与页眉页脚清理回归。"""

from __future__ import annotations

import fitz
import pytest

from app.services import ocr_service

FOOTER = "软考刘杰（大 D）老师 985 毕业学霸直播带课 官网地址 www.ivban.com"


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


def test_ocr_pdf_pages_removes_repeated_footer(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, pages=4)
    pages = iter(
        f"第 {index} 页正文\n\n这是第 {index} 页的表格内容。\n\n{FOOTER}"
        for index in range(1, 5)
    )
    monkeypatch.setattr(
        ocr_service, "ocr_image_bytes", lambda *args, **kwargs: next(pages)
    )

    text, warnings = ocr_service.ocr_pdf_pages(pdf)

    assert FOOTER not in text
    assert "官网地址" not in text
    assert all(f"第 {index} 页正文" in text for index in range(1, 5))
    assert any("页眉" in item and "页脚" in item for item in warnings)


def test_strip_repeated_furniture_tolerates_spacing_and_punctuation():
    footers = [
        "软考刘杰（大 D）老师 985 毕业学霸直播带课 官网地址 www.ivban.com",
        "软考刘杰(大D)老师985毕业学霸直播带课 官网地址:www.ivban.com",
        "软考刘杰（大D）老师 985毕业 学霸直播带课，官网地址 www.ivban.com",
    ]
    pages = [f"正文 {index}\n{footer}" for index, footer in enumerate(footers, start=1)]

    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)

    assert all("ivban" not in page for page in cleaned)
    assert all(f"正文 {index}" in page for index, page in enumerate(cleaned, start=1))
    assert removed


def test_strip_repeated_furniture_keeps_non_majority_lines():
    header = "| 过程 | 输入 | 工具与技术 | 输出 |"
    pages = [f"{header}\n正文 {index}\n结尾 {index}" for index in (1, 2)]
    pages += [f"正文 {index}\n结尾 {index}" for index in (3, 4, 5)]

    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)

    assert cleaned == pages
    assert removed == []


def test_strip_repeated_furniture_removes_page_numbers():
    pages = [f"第一章 概述\n正文 {index}\n第 {index} 页 共 3 页" for index in (1, 2, 3)]
    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)
    assert all("共 3 页" not in page for page in cleaned)
    assert any("页码" in item for item in removed)

    plain = [f"正文 {index}\n{index}" for index in (1, 2, 3)]
    cleaned, removed = ocr_service.strip_repeated_headers_footers(plain)
    assert cleaned == [f"正文 {index}" for index in (1, 2, 3)]
    assert any("页码" in item for item in removed)


def test_strip_repeated_furniture_keeps_one_off_lines():
    pages = [
        "正文 1\n官网地址 www.example.com",
        "正文 2\n结尾 2",
        "正文 3\n结尾 3",
    ]

    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)

    assert cleaned == pages
    assert removed == []


def test_strip_repeated_furniture_skips_short_documents():
    pages = [f"正文 {index}\n{FOOTER}" for index in (1, 2)]
    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)
    assert cleaned == pages
    assert removed == []
