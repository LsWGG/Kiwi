"""文档解析路由：md/txt 透传，PDF / 图片 / DOCX / DOC 抽文本。

策略：
- 电子原生 PDF 先用 PyMuPDF 快速路径；文本覆盖率过低时尝试 OCR；
- OCR 优先使用「系统设置 → 线上 OCR」（OpenAI 兼容视觉模型），
  未配置或失败时回退本机 tesseract + pytesseract；
- 图片导入直接走 OCR；
- 旧版 .doc 通过 LibreOffice 转为 .docx 后复用 DOCX 解析；
- 所有解析器输出统一 ParsedDocument（含 parse_engine / quality_report）。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.services import ocr_service

IMAGE_TYPES = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}


@dataclass
class ParsedDocument:
    title: str
    text: str
    parse_engine: str = "native"
    parse_quality: str = "clean"  # clean / ocr_aided / review
    warnings: list[str] = field(default_factory=list)
    quality_report: dict = field(default_factory=dict)


class ParseError(Exception):
    pass


def parse_file(
    path: Path,
    file_type: str | None = None,
    force_ocr: bool = False,
) -> ParsedDocument:
    """按文件类型路由解析。

    ``force_ocr`` 仅对 PDF 生效：即使文本层完整也强制走 OCR；图片本身即走 OCR。
    """
    ft = (file_type or path.suffix.lstrip(".")).lower()
    # note：工作区笔记编译前会序列化为 Markdown 快照，按文本解析。
    if ft in ("md", "markdown", "txt", "text", "note"):
        return _parse_text(path)
    if ft == "pdf":
        return _parse_pdf(path, force_ocr=force_ocr)
    if ft in IMAGE_TYPES:
        return _parse_image(path, ft)
    if ft == "docx":
        return _parse_docx(path)
    if ft == "doc":
        return _parse_doc(path)
    raise ParseError(f"不支持的格式：{ft}")


def _parse_text(path: Path) -> ParsedDocument:
    try:
        data = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        data = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem or "未命名文档"
    for line in data.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
    return ParsedDocument(
        title=title,
        text=data,
        parse_engine="native",
        quality_report={
            "chars": len(data),
            "lines": len(data.splitlines()),
            "encoding": "utf-8",
        },
    )


def _local_tesseract_image(image) -> tuple[str, list[str]]:
    try:
        import pytesseract
    except ImportError:
        return "", ["未安装 pytesseract / Pillow，无法执行本地 OCR"]
    if not shutil.which("tesseract"):
        return "", ["未安装 tesseract，无法执行本地 OCR"]
    try:
        langs = pytesseract.get_languages(config="")
    except Exception:  # noqa: BLE001
        langs = []
    lang = "chi_sim+eng" if "chi_sim" in langs else "eng"
    warnings = []
    if "chi_sim" not in langs:
        warnings.append("未安装中文 OCR 语言包（chi_sim），中文识别质量可能较低")
    try:
        return pytesseract.image_to_string(image, lang=lang), warnings
    except Exception as exc:  # noqa: BLE001
        return "", [f"本地 OCR 失败：{exc}"]


def _ocr_pdf(path: Path) -> tuple[str, str, list[str], list[str]]:
    """尝试 OCR。返回 (text, engine, warnings, errors)。"""
    warnings: list[str] = []
    errors: list[str] = []

    # 1) 线上 OCR（用户配置的视觉模型）
    if ocr_service.is_available():
        try:
            text, ocr_warnings = ocr_service.ocr_pdf_pages(path)
            warnings.extend(ocr_warnings)
            if text.strip():
                cfg = ocr_service.current_config()
                return text.strip(), f"online-ocr:{cfg.api_model}", warnings, errors
            errors.append("线上 OCR 未返回文本")
        except ocr_service.OcrError as exc:
            errors.append(str(exc))

    # 2) 本地 tesseract
    try:
        import pytesseract  # noqa: F401
        from PIL import Image
    except ImportError:
        warnings.append("未安装 pytesseract / Pillow，无法对扫描件执行本地 OCR")
        return "", "", warnings, errors
    if not shutil.which("tesseract"):
        warnings.append("未安装 tesseract，无法对扫描件执行本地 OCR")
        return "", "", warnings, errors

    import fitz

    doc = fitz.open(path)
    chunks: list[str] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text, image_warnings = _local_tesseract_image(image)
            chunks.extend(image_warnings)
            chunks.append(text)
    finally:
        doc.close()
    return "\n\n".join(chunks).strip(), "tesseract-ocr", warnings, errors


def _parse_image(path: Path, file_type: str) -> ParsedDocument:
    """图片导入：优先线上 OCR，失败回退本地 tesseract。"""
    warnings: list[str] = []
    errors: list[str] = []
    text = ""
    engine = ""

    if ocr_service.is_available():
        try:
            text = ocr_service.ocr_image_file(path)
            if text.strip():
                engine = f"online-ocr:{ocr_service.current_config().api_model}"
            else:
                errors.append("线上 OCR 未返回文本")
        except ocr_service.OcrError as exc:
            errors.append(str(exc))

    if not text.strip():
        try:
            from PIL import Image

            with Image.open(path) as image:
                text, local_warnings = _local_tesseract_image(image)
            warnings.extend(local_warnings)
            if text.strip():
                engine = "tesseract-ocr"
        except ImportError:
            warnings.append("未安装 Pillow，无法执行本地 OCR")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"本地 OCR 失败：{exc}")

    quality = "ocr_aided" if text.strip() else "review"
    if not text.strip():
        text = f"[图片未能识别文字：{path.name}]"
        warnings.append("未能识别图片文字，请检查 OCR 配置或稍后人工复核")
    if errors:
        warnings.extend(f"线上 OCR：{error}" for error in errors)
    return ParsedDocument(
        title=path.stem,
        text=text,
        parse_engine=engine or "ocr-unavailable",
        parse_quality=quality,
        warnings=warnings,
        quality_report={
            "source_type": file_type,
            "chars": len(text),
            "ocr": bool(engine),
            "engine": engine,
        },
    )


def _parse_pdf(path: Path, force_ocr: bool = False) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise ParseError("PyMuPDF 未安装，无法解析 PDF") from e
    doc = fitz.open(path)
    try:
        pages = [page.get_text("text") for page in doc]
        page_count = len(pages)
    finally:
        doc.close()
    native_text = "\n\n".join(pages).strip()
    text = native_text
    chars = len(native_text)
    coverage = chars / max(page_count, 1)
    warnings: list[str] = []
    engine = "pymupdf"
    quality = "clean"

    # 少于 ~30 字/页视为没有可用的文本层，尝试 OCR；用户勾选强制 OCR 时
    # 即使文本层完整也优先使用 OCR 结果（部分 PDF 文本层乱码 / 不可读）。
    ocr_errors: list[str] = []
    if force_ocr or coverage < 30:
        ocr_text, ocr_engine, ocr_warnings, ocr_errors = _ocr_pdf(path)
        warnings.extend(ocr_warnings)
        if ocr_text:
            text = ocr_text
            engine = ocr_engine
            quality = "ocr_aided"
            warnings.append(
                "已按用户选择强制使用 OCR 解析 PDF"
                if force_ocr
                else "PDF 文本层不足，已使用 OCR 辅助解析"
            )
        elif force_ocr and native_text:
            # OCR 不可用或未识别出文字：保留原生文本，避免反而丢失内容。
            if coverage < 30:
                quality = "review"
            warnings.append(
                "已启用强制 OCR，但 OCR 不可用或未返回文本，已保留 PDF 原生文本层"
            )
        else:
            quality = "review"
            warnings.append("PDF 未能提取到文本，可能为扫描件，需要人工复核")
    if not text.strip():
        text = f"[PDF 未能提取文本：{path.name}]"
        quality = "review"

    # 简单表格结构风险：文本中大量制表符或极短行，提示复核。
    lines = [line for line in text.splitlines() if line.strip()]
    short_ratio = (
        sum(1 for line in lines if len(line.strip()) <= 2) / len(lines) if lines else 0
    )
    if quality == "clean" and short_ratio > 0.5:
        quality = "review"
        warnings.append("检测到大量极短文本行，表格结构可能未正确还原")

    return ParsedDocument(
        title=path.stem,
        text=text,
        parse_engine=engine,
        parse_quality=quality,
        warnings=warnings,
        quality_report={
            "pages": page_count,
            "chars": chars,
            "chars_per_page": round(coverage, 1),
            "text_coverage": "low" if coverage < 30 else "normal",
            "ocr": engine.startswith(("tesseract-ocr", "online-ocr")),
            "ocr_engine": engine if engine.startswith(("tesseract-ocr", "online-ocr")) else None,
            "ocr_errors": ocr_errors,
            "force_ocr": force_ocr,
            "warnings": warnings,
        },
    )


def _parse_docx(path: Path) -> ParsedDocument:
    try:
        import docx
    except ImportError as e:
        raise ParseError("python-docx 未安装，无法解析 DOCX") from e
    try:
        d = docx.Document(str(path))
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"DOCX 解析失败：{e}") from e

    parts: list[str] = []
    headings = 0
    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name or "").lower() if p.style else ""
        if style.startswith("heading") or style.startswith("标题"):
            headings += 1
            level = 1
            digits = "".join(ch for ch in style if ch.isdigit())
            if digits:
                level = max(1, min(6, int(digits)))
            parts.append(f"{'#' * level} {text}")
        else:
            parts.append(text)
    table_count = len(d.tables)
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            parts.append(" | ".join(cells))
    text = "\n".join(parts)
    warnings: list[str] = []
    quality = "clean"
    if not text.strip():
        quality = "review"
        warnings.append("DOCX 中未提取到正文")
    if table_count:
        warnings.append(f"包含 {table_count} 个表格，复杂合并单元格可能降级为纯文本")

    return ParsedDocument(
        title=path.stem,
        text=text,
        parse_engine="python-docx",
        parse_quality=quality,
        warnings=warnings,
        quality_report={
            "paragraphs": len(d.paragraphs),
            "headings": headings,
            "tables": table_count,
            "chars": len(text),
        },
    )


def _parse_doc(path: Path) -> ParsedDocument:
    """旧版 .doc：尝试 LibreOffice 转 docx，失败标记复核。"""
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        return ParsedDocument(
            title=path.stem,
            text=f"[旧版 DOC 需要 LibreOffice 转换：{path.name}]",
            parse_engine="unavailable",
            parse_quality="review",
            warnings=["未安装 LibreOffice，无法转换旧版 .doc；请另存为 .docx"],
            quality_report={"conversion": "unavailable"},
        )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    tmp,
                    str(path),
                ],
                capture_output=True,
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ParsedDocument(
                title=path.stem,
                text=f"[旧版 DOC 转换失败：{path.name}]",
                parse_engine="libreoffice",
                parse_quality="review",
                warnings=[f"LibreOffice 转换异常：{exc}"],
                quality_report={"conversion": "error"},
            )
        converted = Path(tmp) / f"{path.stem}.docx"
        if proc.returncode != 0 or not converted.exists():
            return ParsedDocument(
                title=path.stem,
                text=f"[旧版 DOC 转换失败：{path.name}]",
                parse_engine="libreoffice",
                parse_quality="review",
                warnings=[
                    "LibreOffice 转换失败：" + (proc.stderr or b"").decode("utf-8", "replace")[:200]
                ],
                quality_report={"conversion": "error"},
            )
        parsed = _parse_docx(converted)
        parsed.parse_engine = "libreoffice+python-docx"
        parsed.quality_report = {**parsed.quality_report, "conversion": "docx"}
        return parsed


def parse_bytes(
    data: bytes,
    filename: str,
    file_type: str | None = None,
    force_ocr: bool = False,
) -> ParsedDocument:
    """从字节流解析（上传直传，不落盘）。"""
    suffix = Path(filename).suffix or f".{file_type or 'bin'}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return parse_file(
            Path(tmp.name), file_type or suffix.lstrip("."), force_ocr=force_ocr
        )
