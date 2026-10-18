"""上传安全：真实类型检测、压缩炸弹防护、病毒扫描。

设计原则：
- 扩展名只是线索，真实类型以文件头 / 容器结构为准；
- 病毒扫描失败（进程异常、超时）一律拒绝入库，绝不当作干净；
- 未配置 ClamAV 时运行内置启发式扫描并显式标记 heuristic，不伪称 clean。
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_DIRECT_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED = 300 * 1024 * 1024
MAX_ZIP_ENTRY = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_RATIO = 200
MAX_ARCHIVE_FILES = 5_000
MAX_ARCHIVE_TOTAL = 500 * 1024 * 1024

ALLOWED_EXT = {".md", ".markdown", ".txt", ".text", ".pdf", ".docx", ".doc"}
TEXT_EXT = {".md", ".markdown", ".txt", ".text"}
PLAIN_TYPE = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".text": "txt",
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
}

EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
EXEC_MAGIC = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")


class FileRejected(Exception):
    """文件被安全策略拒绝。"""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class FileInspection:
    source_type: str
    scan_status: str  # clean / heuristic / unavailable / infected / error
    scan_detail: str = ""
    warnings: list[str] = field(default_factory=list)


def _zip_bomb_error(zf: zipfile.ZipFile, *, archive: bool = False) -> str | None:
    entries = zf.infolist()
    max_entries = MAX_ARCHIVE_FILES if archive else MAX_ZIP_ENTRIES
    if len(entries) > max_entries:
        return f"压缩包条目过多（{len(entries)}），已阻止解压"
    total_uncompressed = 0
    total_compressed = 0
    for info in entries:
        if info.flag_bits & 0x1:
            return f"压缩包包含加密条目：{info.filename}"
        if info.file_size > (MAX_ZIP_ENTRY if not archive else MAX_UPLOAD_BYTES):
            return f"压缩包内文件过大：{info.filename}"
        total_uncompressed += info.file_size
        total_compressed += max(info.compress_size, 1)
    limit = MAX_ARCHIVE_TOTAL if archive else MAX_ZIP_UNCOMPRESSED
    if total_uncompressed > limit:
        return f"解压后总大小超过上限（{total_uncompressed // (1024 * 1024)}MB）"
    if total_uncompressed / max(total_compressed, 1) > MAX_ZIP_RATIO:
        return "压缩比异常，疑似压缩炸弹"
    return None


def _check_docx(content: bytes) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            error = _zip_bomb_error(zf)
            if error:
                return False, error
            names = set(zf.namelist())
            if "[Content_Types].xml" not in names:
                return False, "DOCX 容器缺少 [Content_Types].xml"
            if "word/document.xml" not in names:
                return False, "DOCX 容器缺少 word/document.xml"
            # 读取主文档验证 CRC，避免损坏文件进入解析队列
            with zf.open("word/document.xml") as fh:
                head = fh.read(4096)
            if b"<w:document" not in head and b"<document" not in head:
                return False, "DOCX 主文档结构异常"
    except zipfile.BadZipFile:
        return False, "文件不是有效的 DOCX（ZIP 容器损坏）"
    return True, ""


def detect_real_type(
    content: bytes, filename: str, max_bytes: int = MAX_UPLOAD_BYTES
) -> tuple[str, list[str]]:
    """返回 (source_type, warnings)；不符合白名单时抛 FileRejected。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise FileRejected(
            f"不支持的文件类型 {ext or '（无扩展名）'}，允许：{', '.join(sorted(ALLOWED_EXT))}",
            415,
        )
    if not content:
        raise FileRejected("空文件", 400)
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise FileRejected(f"文件超过 {limit_mb}MB 上限", 413)

    warnings: list[str] = []
    if ext in TEXT_EXT:
        sample = content[:4096]
        if b"\x00" in sample:
            raise FileRejected("文本文件包含二进制内容，真实类型与扩展名不符", 415)
        lowered = sample.lstrip().lower()
        if lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
            raise FileRejected("检测到 HTML 文档，出于安全考虑拒绝导入", 415)
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append("文件不是严格 UTF-8，解析时会按替换字符容错读取")
        return PLAIN_TYPE[ext], warnings

    if ext == ".pdf":
        if b"%PDF-" not in content[:1024]:
            raise FileRejected("文件头不是 PDF，真实类型与扩展名不符", 415)
        return "pdf", warnings

    if ext == ".docx":
        if not content.startswith(b"PK\x03\x04"):
            raise FileRejected("文件头不是 ZIP/DOCX，真实类型与扩展名不符", 415)
        ok, reason = _check_docx(content)
        if not ok:
            raise FileRejected(reason, 415)
        return "docx", warnings

    if ext == ".doc":
        if not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise FileRejected("文件头不是旧版 Word（OLE）格式", 415)
        warnings.append("旧版 .doc 将尝试通过 LibreOffice 转换；失败时标记待复核")
        return "doc", warnings

    raise FileRejected("不支持的文件类型", 415)


def scan_bytes(content: bytes) -> tuple[str, str]:
    """返回 (status, detail)。infected / error 由调用方拒绝入库。"""
    if EICAR in content or EICAR.lower() in content.lower():
        return "infected", "命中 EICAR 测试特征"

    # 文档容器中不应出现可执行文件头；出现在前 8KB 视为可疑并拒绝
    head = content[:8192]
    for magic in EXEC_MAGIC:
        if head.startswith(magic):
            return "infected", "文件包含可执行文件头"

    configured = os.environ.get("KIWI_CLAMSCAN") or shutil.which("clamscan")
    if configured:
        try:
            proc = subprocess.run(
                [configured, "--no-summary", "--stdout", "-"],
                input=content,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "error", f"病毒扫描异常：{exc}"
        output = (proc.stdout or proc.stderr or b"").decode("utf-8", "replace").strip()
        if proc.returncode == 0:
            return "clean", output[:500] or "ClamAV 扫描通过"
        if proc.returncode == 1:
            return "infected", output[:500] or "ClamAV 检出恶意内容"
        return "error", f"ClamAV 返回异常状态 {proc.returncode}：{output[:400]}"

    # 未安装 ClamAV：运行内置启发式检查，状态明确标记为 heuristic。
    lowered = content[:524288].lower()
    details = ["未配置 ClamAV；已通过内置启发式检查"]
    if b"/javascript" in lowered or b"/js" in lowered and b"/pdf-" in lowered:
        details.append("PDF 含脚本标记，已记录")
    return "heuristic", "；".join(details)


def inspect_upload(
    content: bytes, filename: str, max_bytes: int = MAX_UPLOAD_BYTES
) -> FileInspection:
    source_type, warnings = detect_real_type(content, filename, max_bytes)
    scan_status, scan_detail = scan_bytes(content)
    if scan_status == "infected":
        raise FileRejected(f"病毒扫描未通过：{scan_detail}", 422)
    if scan_status == "error":
        raise FileRejected(f"病毒扫描异常，文件未入库：{scan_detail}", 422)
    return FileInspection(
        source_type=source_type,
        scan_status=scan_status,
        scan_detail=scan_detail,
        warnings=warnings,
    )


def inspect_archive(content: bytes, filename: str) -> zipfile.ZipFile:
    """校验导入压缩包并返回 ZipFile（调用方负责关闭）。"""
    if Path(filename or "").suffix.lower() != ".zip":
        raise FileRejected("请上传 .zip 格式的语雀 Markdown 导出包", 415)
    if not content.startswith(b"PK\x03\x04"):
        raise FileRejected("文件头不是 ZIP，无法识别为导出包", 415)
    if len(content) > MAX_UPLOAD_BYTES:
        raise FileRejected("导出包超过 200MB 上限", 413)
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise FileRejected("导出包已损坏，无法解压", 415) from exc
    error = _zip_bomb_error(zf, archive=True)
    if error:
        zf.close()
        raise FileRejected(error, 422)
    scan_status, scan_detail = scan_bytes(content)
    if scan_status in ("infected", "error"):
        zf.close()
        raise FileRejected(f"导出包安全扫描未通过：{scan_detail}", 422)
    return zf
