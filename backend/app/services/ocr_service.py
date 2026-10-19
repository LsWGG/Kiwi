"""线上 OCR：调用 OpenAI 兼容的视觉模型识别扫描件 / 图片。

解析器运行在线程中，因此这里使用同步 httpx。配置由系统设置单行表提供，
保存后立即通过 ``configure_runtime`` 生效；未启用时解析器回退到本地
tesseract。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger("kiwi.ocr")

OCR_PROMPT = (
    "请准确提取图片中的全部文字，按阅读顺序输出，保留段落与列表结构；"
    "表格尽量还原为 Markdown 表格。不要添加解释、总结或任何额外说明，"
    "只输出识别到的文字。若图片中没有文字，只输出空字符串。"
)


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
    prompt = OCR_PROMPT
    if cfg.language and cfg.language != "auto":
        prompt += f"\n文档主要语言：{cfg.language}。"
    data_url = f"data:{_mime_for(mime=mime)};base64,{base64.b64encode(image).decode('ascii')}"
    payload = {
        "model": cfg.api_model.strip(),
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
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
    return str(content or "").strip()


def ocr_image_file(path: Path, config: OcrConfig | None = None) -> str:
    return ocr_image_bytes(path.read_bytes(), config=config, mime=_mime_for(path))


def ocr_pdf_pages(
    path: Path, config: OcrConfig | None = None, *, max_pages: int = 200
) -> tuple[str, list[str]]:
    """逐页渲染 PDF 并调用线上 OCR，返回 (文本, 警告)。"""
    import fitz

    cfg = config or _runtime
    warnings: list[str] = []
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise OcrError(f"PDF 打开失败：{exc}") from exc
    chunks: list[str] = []
    try:
        for index, page in enumerate(doc):
            if index >= max_pages:
                warnings.append(f"PDF 超过 {max_pages} 页，仅识别前 {max_pages} 页")
                break
            pix = page.get_pixmap(dpi=200)
            try:
                text = ocr_image_bytes(pix.tobytes("png"), config=cfg, mime="image/png")
            except OcrError:
                raise
            if text:
                chunks.append(text)
    finally:
        doc.close()
    return "\n\n".join(chunks).strip(), warnings


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
