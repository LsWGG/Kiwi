"""线上 OCR：调用 OpenAI 兼容的视觉模型识别扫描件 / 图片。

解析器运行在线程中，因此这里使用同步 httpx。配置由系统设置单行表提供，
保存后立即通过 ``configure_runtime`` 生效；未启用时解析器回退到本地
tesseract。
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger("kiwi.ocr")

# DeepSeek-OCR 等专用 OCR 模型对长提示词很敏感：提示词越复杂越容易输出
# 退化内容（例如成片的 `}}}}`）。这里统一使用模型友好的简短英文指令，
# 识别结果的排版整理交给后续的大模型格式化步骤。
OCR_PROMPT = "Convert the document to markdown."
OCR_MAX_TOKENS = 4096

_GROUNDING_REF_RE = re.compile(r"<\|ref\|>.*?<\|/ref\|>", re.S)
_GROUNDING_DET_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.S)
_CONTROL_TOKEN_RE = re.compile(r"<\|[^|<>]{0,40}\|>")
_BRACE_RUN_RE = re.compile(r"[{}]{6,}")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)
_MEANINGFUL_RE = re.compile(
    r"[0-9A-Za-z㐀-䶿一-鿿぀-ヿ가-힯]"
)
_PUNCT_ONLY_RE = re.compile(r"[\s{}()\[\],;:'\"。，；：、“”‘’]+")
_JSON_TEXT_KEYS = ("text", "markdown", "content", "result", "output", "pages", "data")


def _nested_text(value) -> str:
    """从模型的 JSON 结构化输出里递归提取正文。"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(part for part in (_nested_text(v) for v in value) if part)
    if isinstance(value, dict):
        for key in _JSON_TEXT_KEYS:
            if key in value:
                return _nested_text(value[key])
    return ""


def clean_ocr_content(raw: str) -> str:
    """清洗 OCR 模型输出：去掉 grounding 标记、JSON 外壳与花括号噪声。

    无法恢复出任何有效字符时返回空字符串，由调用方回退到本地 OCR / 原生文本。
    """
    text = str(raw or "").strip()
    if not text:
        return ""

    fenced = _JSON_FENCE_RE.match(text)
    candidate = fenced.group(1).strip() if fenced else text
    if candidate.startswith(("{", "[")):
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            data = None
        if data is not None:
            extracted = _nested_text(data).strip()
            if extracted:
                text = extracted

    text = _GROUNDING_REF_RE.sub("", text)
    text = _GROUNDING_DET_RE.sub("", text)
    text = _CONTROL_TOKEN_RE.sub("", text)

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not _MEANINGFUL_RE.search(stripped) and _PUNCT_ONLY_RE.fullmatch(stripped):
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = _BRACE_RUN_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not _MEANINGFUL_RE.search(text):
        return ""
    return text


class OcrError(Exception):
    pass


@dataclass
class OcrConfig:
    enabled: bool = False
    provider: str = "openai"
    api_base: str = ""
    api_key: str = ""
    api_model: str = ""
    timeout: float = 120.0
    language: str = "auto"

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.api_base.strip() and self.api_model.strip())


_runtime = OcrConfig()


def configure_runtime(config: OcrConfig | None) -> None:
    global _runtime
    _runtime = config or OcrConfig()


def current_config() -> OcrConfig:
    return _runtime


def is_available() -> bool:
    return _runtime.available


def _endpoint(base: str) -> str:
    base = base.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _mime_for(path: Path | None = None, mime: str | None = None) -> str:
    if mime:
        return mime
    if path is not None:
        ext = path.suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(ext, "image/png")
    return "image/png"


def ocr_image_bytes(image: bytes, config: OcrConfig | None = None, mime: str | None = None) -> str:
    cfg = config or _runtime
    if not cfg.available:
        raise OcrError("线上 OCR 未配置")
    data_url = f"data:{_mime_for(mime=mime)};base64,{base64.b64encode(image).decode('ascii')}"
    payload = {
        "model": cfg.api_model.strip(),
        "temperature": 0,
        "max_tokens": OCR_MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": OCR_PROMPT},
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    try:
        with httpx.Client(timeout=httpx.Timeout(max(5.0, cfg.timeout))) as client:
            response = client.post(_endpoint(cfg.api_base), json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise OcrError(f"OCR 接口请求失败：{exc}") from exc
    if response.status_code >= 400:
        detail = response.text[:300]
        raise OcrError(f"OCR 接口返回 {response.status_code}：{detail}")
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise OcrError("OCR 接口返回结构无法识别") from exc
    if isinstance(content, list):
        # 部分服务商返回分段内容
        content = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    return clean_ocr_content(str(content or ""))


def ocr_image_file(path: Path, config: OcrConfig | None = None) -> str:
    return ocr_image_bytes(path.read_bytes(), config=config, mime=_mime_for(path))


def ocr_pdf_pages(
    path: Path,
    config: OcrConfig | None = None,
    *,
    max_pages: int = 200,
    dpi: int = 150,
) -> tuple[str, list[str]]:
    """逐页渲染 PDF 并调用线上 OCR，返回 (文本, 警告)。

    单页失败不会中断整份文档：记录页码后继续识别，避免一页超时导致
    整本扫描件回退到不可用的原生文本层。全部页面都失败时才抛 OcrError。
    150 DPI 对扫描件已足够，且页面图更小、单页耗时明显低于 200 DPI。
    """
    import fitz

    cfg = config or _runtime
    warnings: list[str] = []
    errors: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"PDF 打开失败：{exc}") from exc
    chunks: list[str] = []
    try:
        for index, page in enumerate(doc, start=1):
            if index > max_pages:
                warnings.append(f"PDF 超过 {max_pages} 页，仅识别前 {max_pages} 页")
                break
            pix = page.get_pixmap(dpi=dpi)
            try:
                text = ocr_image_bytes(pix.tobytes("png"), config=cfg, mime="image/png")
            except OcrError as exc:
                errors.append(f"第 {index} 页：{exc}")
                warnings.append(f"第 {index} 页 OCR 失败，已跳过：{exc}")
                continue
            if text:
                chunks.append(text)
    finally:
        doc.close()
    text = "\n\n".join(chunks).strip()
    if not text and errors:
        raise OcrError(f"全部页面 OCR 失败（共 {len(errors)} 页）：{errors[0]}")
    return text, warnings


def test_connection(config: OcrConfig) -> tuple[bool, str, str]:
    """用内置测试页验证配置；返回 (ok, message, sample_text)。"""
    if not config.api_base.strip() or not config.api_model.strip():
        return False, "请填写接口地址与模型名", ""
    try:
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=360, height=120)
        page.insert_text((24, 60), "KIWI OCR TEST 123", fontsize=20)
        png = page.get_pixmap(dpi=150).tobytes("png")
        doc.close()
    except Exception:  # noqa: BLE001
        # PyMuPDF 异常时退回 1x1 像素图，仍可验证鉴权与模型可用性。
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ZkAAAAASUVORK5CYII="
        )
    try:
        text = ocr_image_bytes(png, config=config)
    except OcrError as exc:
        return False, str(exc), ""
    if not text:
        return False, "接口返回空内容，请确认模型支持图片输入", ""
    return True, "连接成功，已返回识别结果", text[:200]
