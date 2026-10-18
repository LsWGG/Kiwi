"""Notebook 文档与 Jupyter `.ipynb` 的双向转换。

内部结构保存在 ``note.props_json.notebook_doc``：单元格、输出与执行计数都是
纯数据，便于自动保存与导出；不依赖 nbformat 运行时，减少依赖面。
"""

from __future__ import annotations

import uuid
from typing import Any

MAX_CELLS = 500
MAX_SOURCE_CHARS = 200_000
MAX_OUTPUT_CHARS = 400_000
DEFAULT_LANGUAGE = "python"


def _cell_id(raw: Any) -> str:
    value = str(raw or "").strip()
    if value and len(value) <= 80:
        return value
    return f"cell-{uuid.uuid4().hex[:10]}"


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value or "")


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value or "")


def _cap(value: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return value if len(value) <= limit else value[:limit] + "\n…（输出已截断）"


def _data_value(data: dict, *keys: str) -> str:
    for key in keys:
        if key in data and data[key] is not None:
            return _join(data[key])
    return ""


def _convert_output(raw: dict) -> dict | None:
    kind = str(raw.get("output_type") or "")
    if kind == "stream":
        text = _cap(_join(raw.get("text")))
        if not text:
            return None
        name = "stderr" if raw.get("name") == "stderr" else "stdout"
        return {"type": "stream", "name": name, "text": text}
    if kind == "error":
        trace = raw.get("traceback") or []
        text = "\n".join(str(line) for line in trace) if isinstance(trace, list) else ""
        if not text:
            text = f"{raw.get('ename') or 'Error'}: {raw.get('evalue') or ''}".strip()
        return {"type": "error", "text": _cap(text)}
    if kind in ("execute_result", "display_data"):
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        text = _data_value(data, "text/plain")
        html = _data_value(data, "text/html")
        image = _data_value(data, "image/png")
        if not (text or html or image):
            return None
        output: dict[str, Any] = {
            "type": "execute_result" if kind == "execute_result" else "display_data",
            "text": _cap(text),
            "html": _cap(html),
        }
        if image:
            output["image"] = {"mime": "image/png", "data": image}
        return output
    return None


def doc_from_ipynb(payload: dict) -> dict:
    """把 nbformat 4 文档转换为内部 notebook_doc。"""
    if not isinstance(payload, dict):
        raise ValueError("Notebook 文件格式无效")
    raw_cells = payload.get("cells")
    if not isinstance(raw_cells, list):
        raise ValueError("Notebook 缺少 cells 列表")
    if len(raw_cells) > MAX_CELLS:
        raise ValueError(f"Notebook 单元格超过 {MAX_CELLS} 个")

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    kernel = metadata.get("kernelspec") if isinstance(metadata.get("kernelspec"), dict) else {}
    language = str(
        kernel.get("language")
        or (metadata.get("language_info") or {}).get("name")
        or DEFAULT_LANGUAGE
    )[:40]

    cells: list[dict[str, Any]] = []
    for raw in raw_cells:
        if not isinstance(raw, dict):
            continue
        cell_type = str(raw.get("cell_type") or "code")
        if cell_type not in ("code", "markdown"):
            # raw / heading 等旧格式按 Markdown 展示，避免导入后内容丢失
            cell_type = "markdown"
        source = _cap(_join(raw.get("source")), MAX_SOURCE_CHARS)
        cell: dict[str, Any] = {
            "id": _cell_id(raw.get("id")),
            "type": cell_type,
            "source": source,
        }
        if cell_type == "code":
            count = raw.get("execution_count")
            cell["execution_count"] = count if isinstance(count, int) else None
            outputs = raw.get("outputs") if isinstance(raw.get("outputs"), list) else []
            cell["outputs"] = [
                converted
                for converted in (_convert_output(item) for item in outputs if isinstance(item, dict))
                if converted is not None
            ][:100]
        cells.append(cell)

    return {
        "version": 1,
        "language": language or DEFAULT_LANGUAGE,
        "cells": cells,
    }


def _nb_output(output: dict) -> dict | None:
    kind = str(output.get("type") or "")
    if kind == "stream":
        name = "stderr" if output.get("name") == "stderr" else "stdout"
        return {
            "output_type": "stream",
            "name": name,
            "text": str(output.get("text") or "").splitlines(keepends=True),
        }
    if kind == "error":
        text = str(output.get("text") or "")
        lines = text.splitlines()
        return {
            "output_type": "error",
            "ename": "Error",
            "evalue": lines[-1] if lines else "",
            "traceback": lines,
        }
    if kind in ("execute_result", "display_data"):
        data: dict[str, Any] = {}
        if output.get("text"):
            data["text/plain"] = str(output["text"]).splitlines(keepends=True)
        if output.get("html"):
            data["text/html"] = str(output["html"]).splitlines(keepends=True)
        image = output.get("image")
        if isinstance(image, dict) and image.get("data"):
            data["image/png"] = str(image["data"])
        if not data:
            return None
        result = {
            "output_type": "execute_result" if kind == "execute_result" else "display_data",
            "data": data,
            "metadata": {},
        }
        if kind == "execute_result":
            result["execution_count"] = output.get("execution_count")
        return result
    return None


def doc_to_ipynb(doc: dict, *, title: str = "Notebook") -> dict:
    """把内部 notebook_doc 转换为 nbformat 4.5 文档。"""
    cells: list[dict[str, Any]] = []
    for raw in doc.get("cells") or []:
        if not isinstance(raw, dict):
            continue
        cell_type = "code" if raw.get("type") == "code" else "markdown"
        source = str(raw.get("source") or "")
        base: dict[str, Any] = {
            "cell_type": cell_type,
            "id": _cell_id(raw.get("id")),
            "metadata": {},
            "source": source.splitlines(keepends=True),
        }
        if cell_type == "code":
            base["execution_count"] = raw.get("execution_count")
            outputs = raw.get("outputs") if isinstance(raw.get("outputs"), list) else []
            base["outputs"] = [
                converted
                for converted in (_nb_output(item) for item in outputs if isinstance(item, dict))
                if converted is not None
            ]
        cells.append(base)

    language = str(doc.get("language") or DEFAULT_LANGUAGE)
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3" if language == "python" else language,
                "language": language,
                "name": "python3" if language == "python" else language,
            },
            "language_info": {"name": language},
            "title": title,
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
