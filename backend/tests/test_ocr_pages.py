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


def _ocr_config() -> ocr_service.OcrConfig:
    return ocr_service.OcrConfig(
        enabled=True,
        api_base="http://127.0.0.1:1/v1",
        api_model="deepseek-ocr",
    )


def test_ocr_pdf_pages_skips_failed_page(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf)
    calls: list[int] = []

    def fake_ocr(image, config=None, mime=None):
        calls.append(1)
        # 失败页会做一次重试，因此第 2、3 次调用都属于第 2 页。
        if len(calls) in (2, 3):
            raise ocr_service.OcrError("模拟超时")
        return "text-1" if len(calls) == 1 else "text-3"

    monkeypatch.setattr(ocr_service, "ocr_image_bytes", fake_ocr)
    text, warnings = ocr_service.ocr_pdf_pages(pdf)

    assert "text-1" in text
    assert "text-3" in text
    assert "text-2" not in text
    assert "第 2 页 OCR 未识别" in text
    assert any("第 2 页" in item for item in warnings)


def test_ocr_pdf_pages_retries_transient_failure(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, pages=1)
    attempts: list[int] = []

    def fake_ocr(image, config=None, mime=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise ocr_service.OcrError("模拟 503", status_code=503)
        return "重试成功"

    monkeypatch.setattr(ocr_service, "ocr_image_bytes", fake_ocr)
    text, _ = ocr_service.ocr_pdf_pages(pdf)

    assert "重试成功" in text
    assert len(attempts) == 2


def test_ocr_pdf_pages_falls_back_to_native_text(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, pages=2)
    pages = iter(["识别一", ""])

    def fake_ocr(image, config=None, mime=None):
        return next(pages)

    monkeypatch.setattr(ocr_service, "ocr_image_bytes", fake_ocr)
    text, warnings = ocr_service.ocr_pdf_pages(
        pdf, native_pages=["原生一", "原生二"]
    )

    assert "识别一" in text
    assert "原生二" in text
    assert any("回退 PDF 原生文本层" in item for item in warnings)


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
    pages = [f"正文 {index}\n第一章 概述" for index in (1, 2)]
    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)
    assert cleaned == pages
    assert removed == []


def test_strip_strong_footer_in_two_page_document():
    pages = [f"正文 {index}\n{FOOTER}" for index in (1, 2)]

    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)

    assert cleaned == ["正文 1", "正文 2"]
    assert any("ivban" in item for item in removed)


def test_strip_page_numbers_in_two_page_document():
    pages = [f"正文 {index}\n第 {index} 页 共 2 页" for index in (1, 2)]

    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)

    assert cleaned == ["正文 1", "正文 2"]
    assert any("页码" in item for item in removed)


def test_strip_repeated_furniture_ignores_changing_page_number_in_header():
    pages = [
        f"公司内部资料 第 {index} 页\n正文 {index}\n结尾 {index}"
        for index in (1, 2, 3)
    ]

    cleaned, removed = ocr_service.strip_repeated_headers_footers(pages)

    assert all("公司内部资料" not in page for page in cleaned)
    assert all(f"正文 {index}" in page for index, page in enumerate(cleaned, start=1))
    assert removed


def test_parse_grounding_boxes_scales_and_filters():
    boxes = ocr_service._parse_grounding_boxes(
        "<|ref|>image<|/ref|><|det|>[[100,200,500,600]]<|/det|>"
        "<|ref|>logo<|/ref|><|det|>[[0,0,50,50]]<|/det|>"
        "<|ref|>text<|/ref|><|det|>[[10,10,900,900]]<|/det|>",
        width=1000,
        height=2000,
        model="deepseek-ocr",
    )

    assert boxes == [(100.0, 400.0, 500.0, 1200.0)]
    assert ocr_service._parse_grounding_boxes(
        "<|ref|>image<|/ref|><|det|>[[0.1,0.2,0.5,0.6]]<|/det|>",
        width=1000,
        height=1000,
    ) == [(100.0, 200.0, 500.0, 600.0)]


def test_ocr_pdf_pages_extracts_embedded_image(tmp_path, monkeypatch):
    pdf = tmp_path / "with-image.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((72, 72), "正文")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(100, 150, 300, 350), pixmap=pix)
    doc.save(str(pdf))
    doc.close()

    def fake_grounded(image, *, width, height, config=None, mime=None):
        return ocr_service.OcrImageResult(text="第 1 页正文")

    monkeypatch.setattr(ocr_service, "ocr_image_grounded", fake_grounded)
    sink = ocr_service.FigureSink(directory=tmp_path / "media", url_prefix="/media/kb")
    text, _ = ocr_service.ocr_pdf_pages(
        pdf,
        _ocr_config(),
        figure_sink=sink,
        extract_figures=True,
    )

    assert "第 1 页正文" in text
    assert "![第 1 页图 1](/media/kb/ocr-" in text
    saved = list((tmp_path / "media").glob("ocr-*.png"))
    assert len(saved) == 1 and saved[0].stat().st_size > 0


def test_ocr_pdf_pages_keeps_pages_beyond_max_pages(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf, pages=3)
    monkeypatch.setattr(
        ocr_service, "ocr_image_bytes", lambda *args, **kwargs: "识别文本"
    )

    text, warnings = ocr_service.ocr_pdf_pages(
        pdf,
        max_pages=2,
        native_pages=["原生一", "原生二", "原生三"],
    )

    assert "原生三" in text
    assert any("超出 OCR 上限" in item for item in warnings)


def test_ocr_pdf_pages_crops_grounding_box(tmp_path, monkeypatch):
    pdf = tmp_path / "grounding.pdf"
    _make_pdf(pdf, pages=1)

    def fake_grounded(image, *, width, height, config=None, mime=None):
        return ocr_service.OcrImageResult(
            text="第 1 页正文",
            boxes=[(100.0, 100.0, 500.0, 500.0)],
        )

    monkeypatch.setattr(ocr_service, "ocr_image_grounded", fake_grounded)
    sink = ocr_service.FigureSink(directory=tmp_path / "media", url_prefix="/media/kb")
    text, _ = ocr_service.ocr_pdf_pages(
        pdf,
        _ocr_config(),
        figure_sink=sink,
        extract_figures=True,
    )

    assert "![第 1 页图块" in text
    assert len(list((tmp_path / "media").glob("ocr-*.png"))) == 1
