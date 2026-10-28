"""线上 OCR：调用 OpenAI 兼容的视觉模型识别扫描件 / 图片。

解析器运行在线程中，因此这里使用同步 httpx。配置由系统设置单行表提供，
保存后立即通过 ``configure_runtime`` 生效；未启用时解析器回退到本地
tesseract。
"""

from __future__ import annotations

import base64
import json
import logging
import math
import re
import time
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger("kiwi.ocr")

# DeepSeek-OCR 等专用 OCR 模型对长提示词很敏感：提示词越复杂越容易输出
# 退化内容（例如成片的 `}}}}`）。这里统一使用模型友好的简短英文指令，
# 识别结果的排版整理交给后续的大模型格式化步骤。
OCR_PROMPT = "Convert the document to markdown."
# 需要同时提取图块位置时使用 grounding 模式；DeepSeek-OCR 会在正文中
# 输出 `<|ref|>image<|/ref|><|det|>[[x1,y1,x2,y2]]<|/det|>` 标记。
OCR_GROUNDING_PROMPT = "<|grounding|>Convert the document to markdown."
OCR_MAX_TOKENS = 8192

_GROUNDING_REF_RE = re.compile(r"<\|ref\|>.*?<\|/ref\|>", re.S)
_GROUNDING_DET_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.S)
_GROUNDING_PAIR_RE = re.compile(
    r"<\|ref\|>\s*(.*?)\s*<\|/ref\|>\s*<\|det\|>\s*(\[\[.*?\]\]|\[.*?\])\s*<\|/det\|>",
    re.S,
)
_CONTROL_TOKEN_RE = re.compile(r"<\|[^|<>]{0,40}\|>")
_BRACE_RUN_RE = re.compile(r"[{}]{6,}")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)
_MEANINGFUL_RE = re.compile(
    r"[0-9A-Za-z㐀-䶿一-鿿぀-ヿ가-힯]"
)
_PUNCT_ONLY_RE = re.compile(r"[\s{}()\[\],;:'\"。，；：、“”‘’]+")
_JSON_TEXT_KEYS = ("text", "markdown", "content", "result", "output", "pages", "data")

# 图块标签：只裁出图片 / 图表类区域，表格与正文仍交给 Markdown 排版。
_FIGURE_LABEL_RE = re.compile(
    r"(image|figure|fig\.?|chart|diagram|picture|photo|illustration|图|图片|图表|示意图)",
    re.I,
)
_SKIP_FIGURE_LABEL_RE = re.compile(r"(logo|icon|watermark|qr|二维码|标志|图标|水印)", re.I)
# 两页文档无法靠「多数页重复」判断，但对含网址 / 邮箱 / 版权 / 联系方式的
# 重复行可以高置信度认定为页脚。
_SHORT_DOC_FURNITURE_RE = re.compile(
    r"https?://|www\.|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+|©|版权|电话|热线|官网|地址",
    re.I,
)

# 页眉 / 页脚判定：只检查每页开头和结尾的少量非空行，并要求同一行在
# 多数页面重复出现。不匹配具体文字或关键词，完全由跨页重复与位置决定。
_FURNITURE_ZONE_LINES = 4
_MIN_FURNITURE_LEN = 4
_REPEAT_RATIO = 0.5
_NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
_PAGE_NUMBER_INLINE_RE = re.compile(
    r"(?:第\s*\d{1,4}\s*页(?:\s*[/／,，]?\s*共\s*\d{1,4}\s*页?)?"
    r"|page\s*\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?"
    r"|\b\d{1,4}\s*[/／]\s*\d{1,4}\s*页?)",
    re.I,
)
_PAGE_NUMBER_RE = re.compile(
    r"^(?:"
    r"第\s*\d{1,4}\s*页(?:\s*[/／,，]?\s*共\s*\d{1,4}\s*页?)?"
    r"|\d{1,4}\s*[/／]\s*\d{1,4}\s*页?"
    r"|page\s*\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?"
    r")$",
    re.I,
)


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


def _normalize_furniture_line(line: str) -> str:
    """归一化全半角、空白与标点，避免 OCR 的细微差异导致漏判。

    页眉 / 页脚里的页码逐页变化，先掩掉「第 N 页」「Page N of M」「3/10」
    这类片段再比较，否则同一页脚永远无法被判为重复。
    """
    text = unicodedata.normalize("NFKC", line)
    text = _PAGE_NUMBER_INLINE_RE.sub(" ", text)
    return _NON_WORD_RE.sub("", text).casefold()


def _furniture_zone_indexes(lines: list[str]) -> set[int]:
    """返回每页开头 / 结尾若干非空行的下标，作为页眉页脚候选区。"""
    indexes = [index for index, line in enumerate(lines) if line.strip()]
    return set(indexes[:_FURNITURE_ZONE_LINES] + indexes[-_FURNITURE_ZONE_LINES:])


def _is_page_number(line: str, page_count: int) -> bool:
    value = line.strip().strip("-—_– ")
    if not value:
        return False
    if value.isdigit():
        return 1 <= int(value) <= page_count
    return bool(_PAGE_NUMBER_RE.match(value))


def _repeat_threshold(page_count: int) -> int:
    return max(3, math.ceil(page_count * _REPEAT_RATIO))


def strip_repeated_headers_footers(pages: list[str]) -> tuple[list[str], list[str]]:
    """移除各页顶部 / 底部重复出现的页眉、页脚与页码。

    OCR 逐页识别会把每页都有的页脚文字带进正文。这里不匹配任何具体文字：
    只考察每页前 / 后若干非空行，同一行去掉空白、全半角与标点差异后在
    至少一半页面重复出现，才判定为页眉页脚。
    这样不会把只在正文中出现一次的网址或句子误删。页码因逐页变化无法
    靠重复判断，另按通用的「第 N 页 / Page N of M」形式识别。
    少于 3 页的文档无法可靠判断重复，保持原样。

    返回 ``(清理后的页面列表, 被移除内容的示例)``。
    """
    if len(pages) < 2:
        return list(pages), []
    if len(pages) < 3:
        # 两页文档无法可靠判断普通重复行，但纯页码、以及含网址 / 邮箱 /
        # 版权 / 联系方式的重复页脚可以高置信度移除。
        short_hits: dict[str, set[int]] = defaultdict(set)
        short_samples: dict[str, str] = {}
        for page_index, page in enumerate(pages):
            lines = page.splitlines()
            for line_index in _furniture_zone_indexes(lines):
                line = lines[line_index]
                if not _SHORT_DOC_FURNITURE_RE.search(line):
                    continue
                normalized = _normalize_furniture_line(line)
                if len(normalized) < _MIN_FURNITURE_LEN:
                    continue
                short_hits[normalized].add(page_index)
                short_samples.setdefault(normalized, line.strip())
        short_repeated = {
            key for key, indexes in short_hits.items() if len(indexes) >= len(pages)
        }
        cleaned: list[str] = []
        page_number_hits = 0
        for page in pages:
            lines = page.splitlines()
            zone = _furniture_zone_indexes(lines)
            kept: list[str] = []
            for index, line in enumerate(lines):
                if index in zone:
                    if _is_page_number(line, len(pages)):
                        page_number_hits += 1
                        continue
                    if _normalize_furniture_line(line) in short_repeated:
                        continue
                kept.append(line)
            page_text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
            if not page_text and _MEANINGFUL_RE.search(page):
                page_text = page.strip()
            cleaned.append(page_text)
        removed = [short_samples[key] for key in short_repeated]
        if page_number_hits:
            removed.append(f"页码（{page_number_hits} 处）")
        return cleaned, removed

    hits: dict[str, set[int]] = defaultdict(set)
    samples: dict[str, str] = {}
    for page_index, page in enumerate(pages):
        lines = page.splitlines()
        for line_index in _furniture_zone_indexes(lines):
            line = lines[line_index]
            normalized = _normalize_furniture_line(line)
            if len(normalized) < _MIN_FURNITURE_LEN:
                continue
            hits[normalized].add(page_index)
            samples.setdefault(normalized, line.strip())

    repeated = [
        key
        for key, page_indexes in hits.items()
        if len(page_indexes) >= _repeat_threshold(len(pages))
    ]
    repeated_set = set(repeated)
    removed: list[str] = [samples[key] for key in repeated]
    page_number_hits = 0

    cleaned: list[str] = []
    for page in pages:
        lines = page.splitlines()
        zone = _furniture_zone_indexes(lines)
        kept: list[str] = []
        for index, line in enumerate(lines):
            if index in zone:
                is_page_number = _is_page_number(line, len(pages))
                if _normalize_furniture_line(line) in repeated_set or is_page_number:
                    if is_page_number:
                        page_number_hits += 1
                    continue
            kept.append(line)
        page_text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
        # 保守兜底：如果清理后整页为空，说明命中规则覆盖了整页内容，
        # 宁可保留原页（由调用方后续标记）也不要静默丢掉一页。
        if not page_text and _MEANINGFUL_RE.search(page):
            page_text = page.strip()
        cleaned.append(page_text)

    if page_number_hits:
        removed.append(f"页码（{page_number_hits} 处）")
    return cleaned, removed


class OcrError(Exception):
    """OCR 调用失败；``status_code`` 用于判断是否值得重试。"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class OcrImageResult:
    """单张图片的识别结果。

    ``boxes`` 是从 grounding 标记里解析出的图块坐标，已换算为像素坐标；
    ``truncated`` 表示模型输出达到 max_tokens 上限，正文可能被截断。
    """

    text: str
    boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    truncated: bool = False


@dataclass
class FigureSink:
    """将 PDF 中裁剪出的图片写入上传目录，并生成 Markdown 图片链接。"""

    directory: Path
    url_prefix: str


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
    # 桌面版默认离线：在线 OCR 一律不可用，解析器会回退本地 tesseract。
    if settings.desktop_mode:
        return False
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


def _post_ocr(
    image: bytes,
    cfg: OcrConfig,
    *,
    prompt: str,
    width: int = 0,
    height: int = 0,
    mime: str | None = None,
) -> OcrImageResult:
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
                    {"type": "text", "text": prompt},
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
        raise OcrError(
            f"OCR 接口返回 {response.status_code}：{detail}",
            status_code=response.status_code,
        )
    try:
        data = response.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise OcrError("OCR 接口返回结构无法识别") from exc
    if isinstance(content, list):
        # 部分服务商返回分段内容
        content = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    raw = str(content or "")
    finish_reason = str(choice.get("finish_reason") or "") if isinstance(choice, dict) else ""
    return OcrImageResult(
        text=clean_ocr_content(raw),
        boxes=_parse_grounding_boxes(raw, width, height, cfg.api_model),
        truncated=finish_reason == "length",
    )


def _check_online_ocr(cfg: OcrConfig) -> None:
    if settings.desktop_mode:
        raise OcrError("桌面版已禁用在线 OCR，请安装本地 Tesseract 或改用 Web 部署")
    if not cfg.available:
        raise OcrError("线上 OCR 未配置")


def ocr_image_bytes(image: bytes, config: OcrConfig | None = None, mime: str | None = None) -> str:
    cfg = config or _runtime
    _check_online_ocr(cfg)
    return _post_ocr(image, cfg, prompt=OCR_PROMPT, mime=mime).text


def ocr_image_grounded(
    image: bytes,
    *,
    width: int,
    height: int,
    config: OcrConfig | None = None,
    mime: str | None = None,
) -> OcrImageResult:
    """识别图片并返回图块坐标；需要 DeepSeek-OCR 一类支持 grounding 的模型。"""
    cfg = config or _runtime
    _check_online_ocr(cfg)
    return _post_ocr(
        image,
        cfg,
        prompt=OCR_GROUNDING_PROMPT,
        width=width,
        height=height,
        mime=mime,
    )


def ocr_image_file(path: Path, config: OcrConfig | None = None) -> str:
    return ocr_image_bytes(path.read_bytes(), config=config, mime=_mime_for(path))


_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_MAX_FIGURES_PER_PAGE = 12


def supports_grounding(model: str) -> bool:
    """只有明确支持 grounding 标记的模型才使用图块定位提示词。

    其他视觉模型强行注入 ``<|grounding|>`` 可能被当成普通文本，反而降低
    识别质量；这类模型仍可裁剪 PDF 内嵌图片，只是不做扫描页图块定位。
    """
    name = (model or "").casefold()
    return "deepseek" in name or "dots" in name


def _retry_ocr(call, *, attempts: int = 2):
    """对超时 / 限流 / 5xx 做一次轻量重试；鉴权等确定性错误直接失败。"""
    last: OcrError | None = None
    for attempt in range(attempts):
        try:
            return call()
        except OcrError as exc:
            last = exc
            if exc.status_code is not None and exc.status_code not in _RETRYABLE_STATUS:
                raise
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    if last is None:  # pragma: no cover - attempts >= 1
        raise OcrError("OCR 调用失败")
    raise last


def _parse_grounding_boxes(
    raw: str,
    width: int,
    height: int,
    model: str = "",
) -> list[tuple[float, float, float, float]]:
    """从 DeepSeek-OCR grounding 输出中解析图片类图块，换算为像素坐标。

    常见坐标有三种：0–1、0–1000（DeepSeek-OCR 默认）和页面像素。这里按
    数值范围判断；模型名包含 deepseek 时优先按 0–1000 处理。
    """
    if width <= 0 or height <= 0:
        return []
    boxes: list[tuple[float, float, float, float]] = []
    for raw_label, payload in _GROUNDING_PAIR_RE.findall(raw or ""):
        label = _CONTROL_TOKEN_RE.sub("", raw_label or "").strip()
        if _SKIP_FIGURE_LABEL_RE.search(label):
            continue
        if not _FIGURE_LABEL_RE.search(label):
            continue
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if isinstance(data, list) and data and isinstance(data[0], (int, float)):
            data = [data]
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, (list, tuple)) or len(item) < 4:
                continue
            try:
                x1, y1, x2, y2 = (float(value) for value in item[:4])
            except (TypeError, ValueError):
                continue
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            largest = max(x2, y2)
            if largest <= 1.5:
                x1, x2 = x1 * width, x2 * width
                y1, y2 = y1 * height, y2 * height
            elif largest <= 1000 and (
                "deepseek" in model.casefold() or width > 1000 or height > 1000
            ):
                x1, x2 = x1 * width / 1000.0, x2 * width / 1000.0
                y1, y2 = y1 * height / 1000.0, y2 * height / 1000.0
            x1 = max(0.0, min(x1, float(width)))
            x2 = max(0.0, min(x2, float(width)))
            y1 = max(0.0, min(y1, float(height)))
            y2 = max(0.0, min(y2, float(height)))
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            area_ratio = ((x2 - x1) * (y2 - y1)) / (width * height)
            if area_ratio < 0.01 or area_ratio > 0.9:
                continue
            boxes.append((x1, y1, x2, y2))
    return boxes


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def repeated_logo_xrefs(doc) -> set[int]:
    """找出在多数页面重复出现的小图（页眉 logo、页脚图标），供裁剪时跳过。"""
    try:
        page_count = len(doc)
    except TypeError:  # pragma: no cover - defensive
        return set()
    if page_count < 2:
        return set()
    counts: dict[int, int] = defaultdict(int)
    max_ratios: dict[int, float] = defaultdict(float)
    for page in doc:
        page_area = float(page.rect.width * page.rect.height) or 1.0
        seen: set[int] = set()
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:  # noqa: BLE001 - 图片信息缺失不影响文字识别
            continue
        for info in infos:
            try:
                xref = int(info.get("xref") or 0)
            except (TypeError, ValueError):
                xref = 0
            if xref <= 0 or xref in seen:
                continue
            seen.add(xref)
            bbox = info.get("bbox") or ()
            if len(bbox) != 4:
                continue
            ratio = max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / page_area
            max_ratios[xref] = max(max_ratios[xref], ratio)
            counts[xref] += 1
    threshold = max(2, math.ceil(page_count * _REPEAT_RATIO))
    return {
        xref
        for xref, count in counts.items()
        if count >= threshold and max_ratios[xref] < 0.15
    }


def _page_figure_rects(page, skip_xrefs: set[int]) -> list:
    """返回页面内值得裁剪的嵌入图片区域（排除整页扫描、小图标与重复 logo）。"""
    import fitz

    page_area = float(page.rect.width * page.rect.height) or 1.0
    rects: list[fitz.Rect] = []
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:  # noqa: BLE001
        return rects
    for info in infos:
        try:
            xref = int(info.get("xref") or 0)
        except (TypeError, ValueError):
            xref = 0
        if xref and xref in skip_xrefs:
            continue
        bbox = info.get("bbox") or ()
        if len(bbox) != 4:
            continue
        try:
            rect = fitz.Rect(*(float(value) for value in bbox)) & page.rect
        except (TypeError, ValueError):
            continue
        if rect.is_empty:
            continue
        width = float(info.get("width") or 0)
        height = float(info.get("height") or 0)
        if width and height and (width < 64 or height < 64):
            continue
        ratio = (rect.width * rect.height) / page_area
        if ratio < 0.02 or ratio > 0.9:
            continue
        if any(_iou(rect, existing) > 0.7 for existing in rects):
            continue
        rects.append(rect)
        if len(rects) >= _MAX_FIGURES_PER_PAGE:
            break
    return rects


def _save_figure(
    sink: FigureSink,
    png: bytes,
    page_no: int,
    index: int,
    *,
    label: str | None = None,
) -> tuple[str, Path]:
    sink.directory.mkdir(parents=True, exist_ok=True)
    name = f"ocr-{uuid.uuid4().hex}.png"
    path = sink.directory / name
    path.write_bytes(png)
    alt = label or f"第 {page_no} 页图 {index}"
    url = f"{sink.url_prefix.rstrip('/')}/{name}"
    return f"![{alt}]({url})", path


def _save_figure_rects(
    page,
    sink: FigureSink,
    rects: list,
    *,
    dpi: int,
    page_no: int,
    warnings: list[str] | None = None,
) -> tuple[list[str], list[Path]]:
    figures: list[str] = []
    paths: list[Path] = []
    for rect in rects:
        try:
            png = page.get_pixmap(clip=rect, dpi=dpi).tobytes("png")
            markdown, saved = _save_figure(sink, png, page_no, len(figures) + 1)
        except Exception as exc:  # noqa: BLE001 - 单张图片失败不影响整页识别
            if warnings is not None:
                warnings.append(f"第 {page_no} 页图片提取失败：{exc}")
            continue
        figures.append(markdown)
        paths.append(saved)
    return figures, paths


def extract_embedded_figures(
    page,
    sink: FigureSink,
    *,
    dpi: int,
    page_no: int,
    skip_xrefs: set[int] | None = None,
    warnings: list[str] | None = None,
) -> tuple[list[str], list[Path]]:
    """裁剪页面内嵌图片并保存，返回 (Markdown 链接, 文件路径)。"""
    return _save_figure_rects(
        page,
        sink,
        _page_figure_rects(page, skip_xrefs or set()),
        dpi=dpi,
        page_no=page_no,
        warnings=warnings,
    )


def save_page_image(
    page,
    sink: FigureSink,
    *,
    dpi: int,
    page_no: int,
    warnings: list[str] | None = None,
) -> tuple[str, Path] | None:
    """保存整页渲染图，供 OCR 失败页兜底，避免页面凭空消失。"""
    try:
        png = page.get_pixmap(dpi=dpi).tobytes("png")
        return _save_figure(
            sink,
            png,
            page_no,
            1,
            label=f"第 {page_no} 页（OCR 未识别）",
        )
    except Exception as exc:  # noqa: BLE001
        if warnings is not None:
            warnings.append(f"第 {page_no} 页整页图保存失败：{exc}")
        return None


def ocr_pdf_pages(
    path: Path,
    config: OcrConfig | None = None,
    *,
    max_pages: int = 200,
    dpi: int = 150,
    native_pages: list[str] | None = None,
    figure_sink: FigureSink | None = None,
    extract_figures: bool = False,
) -> tuple[str, list[str]]:
    """逐页渲染 PDF 并调用线上 OCR，返回 (文本, 警告)。

    每一页都会在结果里占一个位置，不再因为识别失败或返回空内容而让整页
    凭空消失：
    - 单页失败先重试一次，仍失败时回退到该页 PDF 原生文本层；
    - 原生文本层也没有时，插入「本页未识别」占位；
    - 勾选强制 OCR 且提供 ``figure_sink`` 时，裁剪页面内嵌图片，并从
      DeepSeek-OCR 的 grounding 标记中解析图块坐标，图片链接排在对应页
      文字之后；
    - 全部页面都失败（且没有原生文本可回退）时才抛 OcrError，交给解析器
      走本地 tesseract 或标记待人工校对。

    识别完成后会移除各页重复出现的页眉、页脚与页码；图片链接在清理之后
    才拼接，避免被误判为页眉页脚。
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

    use_figures = bool(extract_figures and figure_sink is not None)
    use_grounding = use_figures and supports_grounding(cfg.api_model)
    skip_xrefs = repeated_logo_xrefs(doc) if use_figures else set()
    page_texts: list[str] = []
    page_figures: list[list[str]] = []
    saved_paths: list[Path] = []
    text_pages = 0
    try:
        for index, page in enumerate(doc, start=1):
            if index > max_pages:
                warnings.append(f"PDF 超过 {max_pages} 页，仅识别前 {max_pages} 页")
                break
            try:
                pix = page.get_pixmap(dpi=dpi)
            except Exception as exc:  # noqa: BLE001 - 单页渲染失败不应中断整份文档
                errors.append(f"第 {index} 页渲染失败：{exc}")
                warnings.append(f"第 {index} 页渲染失败：{exc}")
                page_texts.append(f"> 第 {index} 页渲染失败，请对照原文件。")
                page_figures.append([])
                continue

            image_bytes = pix.tobytes("png")
            text = ""
            boxes: list[tuple[float, float, float, float]] = []
            page_error: str | None = None
            try:
                if use_grounding:
                    result = _retry_ocr(
                        lambda: ocr_image_grounded(
                            image_bytes,
                            width=pix.width,
                            height=pix.height,
                            config=cfg,
                            mime="image/png",
                        )
                    )
                    text = result.text
                    boxes = result.boxes
                    if result.truncated:
                        warnings.append(
                            f"第 {index} 页 OCR 输出达到长度上限，内容可能不完整"
                        )
                else:
                    text = _retry_ocr(
                        lambda: ocr_image_bytes(image_bytes, config=cfg, mime="image/png")
                    )
            except OcrError as exc:
                page_error = str(exc)
                errors.append(f"第 {index} 页：{exc}")
                warnings.append(f"第 {index} 页 OCR 失败：{exc}")

            if not text.strip() and native_pages is not None and index <= len(native_pages):
                fallback = (native_pages[index - 1] or "").strip()
                if fallback:
                    text = fallback
                    warnings.append(f"第 {index} 页 OCR 无结果，已回退 PDF 原生文本层")
            if text.strip():
                text_pages += 1

            figures: list[str] = []
            if use_figures and figure_sink is not None:
                embedded_rects = _page_figure_rects(page, skip_xrefs)
                embedded, embedded_paths = _save_figure_rects(
                    page,
                    figure_sink,
                    embedded_rects,
                    dpi=dpi,
                    page_no=index,
                    warnings=warnings,
                )
                figures.extend(embedded)
                saved_paths.extend(embedded_paths)

                scale = dpi / 72.0
                embedded_pixels = [
                    (rect.x0 * scale, rect.y0 * scale, rect.x1 * scale, rect.y1 * scale)
                    for rect in embedded_rects
                ]
                saved_pixels = list(embedded_pixels)
                for box in boxes:
                    if any(_iou(box, existing) > 0.5 for existing in saved_pixels):
                        continue
                    if len(figures) >= _MAX_FIGURES_PER_PAGE:
                        break
                    rect = (
                        fitz.Rect(
                            box[0] * 72.0 / dpi,
                            box[1] * 72.0 / dpi,
                            box[2] * 72.0 / dpi,
                            box[3] * 72.0 / dpi,
                        )
                        & page.rect
                    )
                    if rect.is_empty:
                        continue
                    try:
                        crop = page.get_pixmap(clip=rect, dpi=dpi).tobytes("png")
                        markdown, saved = _save_figure(
                            figure_sink,
                            crop,
                            index,
                            len(figures) + 1,
                            label=f"第 {index} 页图块 {len(figures) + 1}",
                        )
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"第 {index} 页图块裁剪失败：{exc}")
                        continue
                    figures.append(markdown)
                    saved_paths.append(saved)
                    saved_pixels.append(box)

                # 整页失败且没有可回退文本时，至少把整页图保留下来，避免丢页。
                if page_error and not text.strip() and not figures:
                    try:
                        markdown, saved = _save_figure(
                            figure_sink,
                            image_bytes,
                            index,
                            1,
                            label=f"第 {index} 页（OCR 未识别）",
                        )
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"第 {index} 页整页图保存失败：{exc}")
                    else:
                        figures.append(markdown)
                        saved_paths.append(saved)

            if page_error and not text.strip() and not figures:
                text = f"> 第 {index} 页 OCR 未识别，请对照原文件。"

            page_texts.append(text)
            page_figures.append(figures)
    finally:
        doc.close()

    if text_pages == 0 and errors:
        for saved in saved_paths:
            try:
                saved.unlink(missing_ok=True)
            except OSError:
                pass
        raise OcrError(f"全部页面 OCR 失败（共 {len(errors)} 页）：{errors[0]}")

    page_texts, removed = strip_repeated_headers_footers(page_texts)
    if removed:
        warnings.append(f"已移除重复页眉/页脚 {len(removed)} 项：{removed[0][:60]}")

    # 超过单次 OCR 页数上限的部分不再识别，但必须保留在结果里：
    # 有原生文本层就回退原生文本，扫描页至少留下占位，避免整段丢页。
    if native_pages is not None and len(page_texts) < len(native_pages):
        remainder = len(native_pages) - len(page_texts)
        native_kept = 0
        for index in range(len(page_texts) + 1, len(native_pages) + 1):
            fallback = (native_pages[index - 1] or "").strip()
            if fallback:
                page_texts.append(fallback)
                native_kept += 1
            else:
                page_texts.append(
                    f"> 第 {index} 页未做 OCR（超过单次 {max_pages} 页上限），请对照原文件。"
                )
            page_figures.append([])
        if native_kept:
            warnings.append(f"超出 OCR 上限的 {remainder} 页已回退 PDF 原生文本层")
        else:
            warnings.append(f"超出 OCR 上限的 {remainder} 页仅保留页码占位")

    assembled: list[str] = []
    for text, figures in zip(page_texts, page_figures):
        parts = [text.strip(), *figures]
        assembled.append("\n\n".join(part for part in parts if part))
    figure_count = sum(len(items) for items in page_figures)
    if figure_count:
        warnings.append(f"已从 PDF 裁剪 {figure_count} 张图片并插入笔记")
    text = "\n\n".join(part for part in assembled if part).strip()
    return text, warnings


def test_connection(config: OcrConfig) -> tuple[bool, str, str]:
    """用内置测试页验证配置；返回 (ok, message, sample_text)。"""
    if settings.desktop_mode:
        return False, "桌面版已禁用在线 OCR，请安装本地 Tesseract 或改用 Web 部署", ""
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
