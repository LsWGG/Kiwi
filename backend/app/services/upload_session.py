"""分片上传 + 断点续传。

会话元数据落盘为 JSON（单机本地应用，无多副本需求）；
分片按索引写入独立文件，完成时按序合并并校验大小与 sha256。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from app.config import settings
from app.services.file_security import MAX_UPLOAD_BYTES

CHUNK_SIZE = 4 * 1024 * 1024
MAX_CHUNKS = 50
_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


class UploadError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class UploadSession:
    id: str
    kb_id: str
    filename: str
    size: int
    sha256: str
    chunk_size: int
    total_chunks: int
    created_at: str

    @property
    def dir(self) -> Path:
        return _chunks_root() / self.id

    def meta_path(self) -> Path:
        return self.dir / "meta.json"

    def chunk_path(self, index: int) -> Path:
        return self.dir / f"{index:05d}.part"

    def received_chunks(self) -> list[int]:
        found = []
        for index in range(self.total_chunks):
            path = self.chunk_path(index)
            if path.is_file():
                found.append(index)
        return found

    def received_bytes(self) -> int:
        return sum(self.chunk_path(i).stat().st_size for i in self.received_chunks())

    def public(self) -> dict:
        received = self.received_chunks()
        return {
            "upload_id": self.id,
            "filename": self.filename,
            "size": self.size,
            "sha256": self.sha256,
            "chunk_size": self.chunk_size,
            "total_chunks": self.total_chunks,
            "received_chunks": received,
            "received_bytes": self.received_bytes(),
            "completed": len(received) == self.total_chunks,
        }


def _chunks_root() -> Path:
    root = Path(settings.upload_dir) / "chunks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_from_dir(path: Path) -> UploadSession | None:
    if not _SAFE_ID.fullmatch(path.name):
        return None
    meta = path / "meta.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text("utf-8"))
        return UploadSession(**data)
    except (OSError, ValueError, TypeError):
        return None


def _save(session: UploadSession) -> None:
    session.dir.mkdir(parents=True, exist_ok=True)
    session.meta_path().write_text(
        json.dumps(asdict(session), ensure_ascii=False), encoding="utf-8"
    )


def _find_resumable(kb_id: uuid.UUID, filename: str, size: int, fingerprint: str) -> UploadSession | None:
    """同库、同名、同大小、同指纹且已有分片的会话视为可续传。"""
    for path in _chunks_root().iterdir():
        session = _session_from_dir(path)
        if session is None:
            continue
        if (
            session.kb_id == str(kb_id)
            and session.filename == filename
            and session.size == size
            and session.sha256 == fingerprint
            and session.received_chunks()
        ):
            return session
    return None


def init_session(
    kb_id: uuid.UUID,
    filename: str,
    size: int,
    fingerprint: str = "",
) -> UploadSession:
    if not filename or not re.search(r"\.[A-Za-z0-9]+$", filename):
        raise UploadError("文件名缺少扩展名", 415)
    if size <= 0:
        raise UploadError("文件为空", 400)
    if size > MAX_UPLOAD_BYTES:
        raise UploadError("文件超过 200MB 上限", 413)
    if fingerprint and not re.fullmatch(r"[0-9a-f]{64}", fingerprint.lower()):
        raise UploadError("内容指纹格式应为 64 位十六进制", 400)

    if fingerprint:
        existing = _find_resumable(kb_id, filename, size, fingerprint.lower())
        if existing is not None:
            return existing

    total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
    if total_chunks > MAX_CHUNKS:
        raise UploadError("文件分片数超过上限", 413)
    session = UploadSession(
        id=uuid.uuid4().hex,
        kb_id=str(kb_id),
        filename=filename,
        size=size,
        sha256=fingerprint.lower(),
        chunk_size=CHUNK_SIZE,
        total_chunks=total_chunks,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _save(session)
    return session


def load_session(upload_id: str) -> UploadSession:
    if not _SAFE_ID.fullmatch(upload_id or ""):
        raise UploadError("上传会话不存在", 404)
    session = _session_from_dir(_chunks_root() / upload_id)
    if session is None:
        raise UploadError("上传会话不存在", 404)
    return session


def write_chunk(session: UploadSession, index: int, chunk: bytes) -> dict:
    if index < 0 or index >= session.total_chunks:
        raise UploadError("分片序号越界", 416)
    if not chunk:
        raise UploadError("分片内容为空", 400)
    if len(chunk) > session.chunk_size:
        raise UploadError("分片超过 4MB 上限", 413)
    expected = (
        session.chunk_size
        if index < session.total_chunks - 1
        else session.size - session.chunk_size * (session.total_chunks - 1)
    )
    if len(chunk) != expected:
        raise UploadError(
            f"分片 {index} 大小应为 {expected} 字节（实际 {len(chunk)}）", 400
        )
    session.dir.mkdir(parents=True, exist_ok=True)
    tmp = session.chunk_path(index).with_suffix(".tmp")
    tmp.write_bytes(chunk)
    tmp.replace(session.chunk_path(index))
    return session.public()


def assemble(session: UploadSession) -> bytes:
    received = session.received_chunks()
    if len(received) != session.total_chunks:
        missing = sorted(set(range(session.total_chunks)) - set(received))
        raise UploadError(f"分片不完整，缺少：{missing[:10]}", 409)
    data = b"".join(session.chunk_path(i).read_bytes() for i in range(session.total_chunks))
    if len(data) != session.size:
        raise UploadError(
            f"合并后大小不符（期望 {session.size}，实际 {len(data)}）", 400
        )
    if session.sha256:
        actual = sha256(data).hexdigest()
        if actual != session.sha256:
            raise UploadError("内容指纹校验失败，请重新上传", 400)
    return data


def abort_session(session: UploadSession) -> None:
    for index in range(session.total_chunks):
        try:
            session.chunk_path(index).unlink(missing_ok=True)
        except OSError:
            pass
    try:
        session.meta_path().unlink(missing_ok=True)
    except OSError:
        pass
    try:
        session.dir.rmdir()
    except OSError:
        pass
