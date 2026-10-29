"""公开只读分享页接口。

这些路由不依赖登录态，由 ``AccessControlMiddleware`` 的公开前缀放行。
分享 token 是不可猜测的随机凭证；可选访问密码以 PBKDF2 哈希保存。
正文中的 ``/media/...`` 图片会改写为带短期签名的分享地址，密码保护的
分享不会因为图片直链而绕过访问控制。
"""

from __future__ import annotations

import hashlib
import hmac
import mimetypes
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import CollectionRow, Note, NoteCollection, NoteShare
from app.db.session import get_session
from app.schemas.note import SharedNoteOut
from app.services import note_compiler, note_lock

router = APIRouter(prefix="/api/share", tags=["share"])

PASSWORD_WINDOW_SECONDS = 300
PASSWORD_MAX_FAILURES = 10
MEDIA_SIGN_TTL_SECONDS = 6 * 60 * 60
# 数据表公开分享最多带出的行数，避免一次请求序列化整张大表。
MAX_SHARED_DB_ROWS = 500
# 分享正文里可以内联展示的文件类型；其余附件一律以 download 返回，
# 避免把 .html / .js 等主动内容以分享站点的源内联执行。
INLINE_MEDIA_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".bmp",
    ".ico",
    ".svg",
    ".pdf",
    ".txt",
    ".md",
    ".csv",
}

# 进程内密码失败计数：单人部署足够，重启后清零。
_failures: dict[str, list[float]] = {}
MEDIA_RE = re.compile(r"(?<![\w:])/media/([^\"'\s<>)]+)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _load_share(session: AsyncSession, token: str) -> NoteShare:
    share = (
        await session.execute(select(NoteShare).where(NoteShare.token == token))
    ).scalar_one_or_none()
    if share is None:
        raise _error(404, "share_not_found", "分享链接不存在或已被删除")
    if share.revoked_at is not None:
        raise _error(404, "share_revoked", "分享链接已被撤销")
    if share.expires_at <= _now():
        raise _error(410, "share_expired", "分享链接已过期，请联系分享者重新生成")
    return share


def _client_key(request: Request, token: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{token}:{client}"


def _assert_not_throttled(key: str) -> None:
    now = time.monotonic()
    attempts = [item for item in _failures.get(key, []) if now - item < PASSWORD_WINDOW_SECONDS]
    _failures[key] = attempts
    if len(attempts) >= PASSWORD_MAX_FAILURES:
        raise _error(429, "share_password_locked", "密码尝试次数过多，请稍后再试")


def _record_failure(key: str) -> None:
    _failures.setdefault(key, []).append(time.monotonic())


def _verify_password(share: NoteShare, password: str | None, key: str) -> None:
    if not share.has_password:
        return
    if not password:
        raise _error(401, "share_password_required", "该分享需要访问密码")
    _assert_not_throttled(key)
    assert share.password_salt and share.password_hash
    candidate = note_lock.hash_password(password, share.password_salt)
    if not hmac.compare_digest(candidate, share.password_hash):
        _record_failure(key)
        raise _error(401, "share_password_invalid", "访问密码不正确")
    _failures.pop(key, None)


def _media_secret(share: NoteShare) -> bytes:
    # 有密码时把哈希并入密钥，仅服务端可签名；无密码时使用服务端密钥。
    raw = share.password_hash or settings.fernet_key or share.token
    return raw.encode("utf-8")


def _media_expiry(share: NoteShare) -> int:
    now = int(time.time())
    share_expiry = int(share.expires_at.timestamp())
    return max(now + 60, min(share_expiry, now + MEDIA_SIGN_TTL_SECONDS))


def _media_signature(share: NoteShare, path: str, expires_at: int) -> str:
    message = f"{share.id}:{share.token}:{path}:{expires_at}".encode("utf-8")
    return hmac.new(_media_secret(share), message, hashlib.sha256).hexdigest()


def _rewrite_media(body: str, share: NoteShare, expires_at: int) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).split("?", 1)[0].split("#", 1)[0]
        rel = unquote(raw)
        signature = _media_signature(share, rel, expires_at)
        url = (
            f"/api/share/{share.token}/media/{quote(rel, safe='/')}"
            f"?exp={expires_at}&sig={signature}"
        )
        return url

    return MEDIA_RE.sub(replace, body)


def _signed_value(value: object, share: NoteShare, expires_at: int) -> object:
    """递归改写结构化内容里的本地媒体地址（附件、图标等）。"""
    if isinstance(value, str):
        return _rewrite_media(value, share, expires_at)
    if isinstance(value, list):
        return [_signed_value(item, share, expires_at) for item in value]
    if isinstance(value, dict):
        return {
            key: _signed_value(item, share, expires_at)
            for key, item in value.items()
        }
    return value


async def _database_payload(
    session: AsyncSession, note: Note
) -> dict:
    collection = (
        await session.execute(
            select(NoteCollection).where(NoteCollection.note_id == note.id)
        )
    ).scalar_one_or_none()
    base: dict = {
        "name": note.title,
        "description": "",
        "fields": [],
        "rows": [],
        "total_rows": 0,
        "truncated": False,
    }
    if collection is None:
        return {"database": base}

    rows = list(
        (
            await session.execute(
                select(CollectionRow)
                .where(CollectionRow.collection_id == collection.id)
                .order_by(CollectionRow.sort_order, CollectionRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    base.update(
        name=collection.name or note.title,
        description=collection.description or "",
        fields=[
            field
            for field in (collection.schema_json or {}).get("fields") or []
            if isinstance(field, dict)
        ],
        rows=[
            {
                "id": str(row.id),
                "note_id": str(row.note_id) if row.note_id else None,
                "data": row.data or {},
                "sort_order": row.sort_order,
            }
            for row in rows[:MAX_SHARED_DB_ROWS]
        ],
        total_rows=len(rows),
        truncated=len(rows) > MAX_SHARED_DB_ROWS,
    )
    return {"database": base}


async def _build_payload(
    session: AsyncSession, note: Note, share: NoteShare, expires_at: int
) -> dict:
    """按笔记类型构建只读结构化内容；链接 / 附件中的媒体地址统一签名。"""
    props = note.props_json or {}
    if note.kind == "database":
        payload = await _database_payload(session, note)
    elif note.kind == "sheet":
        workbook = props.get("sheet")
        payload = {"workbook": workbook} if isinstance(workbook, dict) else {}
    elif note.kind == "canvas":
        doc = props.get("canvas_doc")
        payload = {"doc": doc} if isinstance(doc, dict) else {}
    elif note.kind == "notebook":
        doc = props.get("notebook_doc")
        payload = {"notebook_doc": doc} if isinstance(doc, dict) else {}
    elif note.kind == "link":
        link = props.get("link")
        payload = {"link": link} if isinstance(link, dict) else {}
    else:
        payload = {}
    signed = _signed_value(payload, share, expires_at)
    return signed if isinstance(signed, dict) else {}


def _strip_title_heading(body: str, title: str) -> str:
    """来源笔记序列化会把标题写成一级标题，分享页已单独展示标题。"""
    lines = body.splitlines()
    if lines and lines[0].strip() == f"# {title}".strip():
        return "\n".join(lines[1:]).lstrip("\n")
    return body


@router.get("/{token}/media/{path:path}")
async def shared_media(
    token: str,
    path: str,
    exp: int,
    sig: str,
    session: AsyncSession = Depends(get_session),
):
    """分享正文引用的本地媒体与附件；必须携带内容响应中下发的签名。

    图片 / PDF / 纯文本内联展示；其他任意后缀（压缩包、Office 文件等）
    以附件下载，保证「只读分享」里的附件可用，同时避免 HTML / JS 之类
    的主动内容在分享域名下以内联文档执行。
    """
    share = await _load_share(session, token)
    if exp < int(time.time()):
        raise _error(410, "share_media_expired", "图片地址已过期，请刷新分享页")
    expected = _media_signature(share, path, exp)
    if not hmac.compare_digest(sig, expected):
        raise _error(404, "share_media_not_found", "图片不存在")

    root = (Path(settings.upload_dir) / "media").resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise _error(404, "share_media_not_found", "图片不存在") from None
    if not target.is_file():
        raise _error(404, "share_media_not_found", "图片不存在")

    suffix = target.suffix.lower()
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if suffix in INLINE_MEDIA_SUFFIXES:
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        # SVG 可以携带脚本：CSP sandbox 让它在被直接打开时也失去脚本能力，
        # 作为 <img> 加载时不受影响。
        if suffix == ".svg":
            headers["Content-Security-Policy"] = "sandbox"
        return FileResponse(target, media_type=media_type, headers=headers)

    filename = target.name
    fallback = filename.encode("ascii", "ignore").decode() or "download"
    headers["Content-Disposition"] = (
        f"attachment; filename=\"{fallback}\"; "
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
    return FileResponse(
        target, media_type="application/octet-stream", headers=headers
    )


@router.get("/{token}", response_model=SharedNoteOut)
async def get_shared_note(
    token: str,
    request: Request,
    response: Response,
    x_share_password: str | None = Header(default=None, alias="X-Share-Password"),
    session: AsyncSession = Depends(get_session),
):
    """返回分享笔记的只读内容；有密码时需 ``X-Share-Password``。"""
    share = await _load_share(session, token)
    throttle_key = _client_key(request, token)
    _verify_password(share, x_share_password, throttle_key)

    note = await session.get(Note, share.note_id)
    if note is None or note.kb_id != share.kb_id or note.status != "active":
        raise _error(404, "share_not_found", "原笔记已被删除或移入回收站")
    if note.is_locked:
        raise _error(403, "share_unavailable", "原笔记已上锁，暂时无法查看分享内容")

    props = note.props_json or {}
    expires_at = _media_expiry(share)
    body = (await note_compiler.build_note_compile_markdown(session, note)).strip()
    body = _strip_title_heading(body, note.title)
    body = _rewrite_media(body, share, expires_at)
    payload = await _build_payload(session, note, share, expires_at)

    share.view_count = (share.view_count or 0) + 1
    share.last_viewed_at = _now()
    await session.commit()

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    return SharedNoteOut(
        title=note.title,
        body_md=body,
        kind=note.kind,
        updated_at=note.updated_at,
        expires_at=share.expires_at,
        has_password=share.has_password,
        emoji=str(props.get("emoji") or "") or None,
        page_prefs=(
            props.get("page_prefs") if isinstance(props.get("page_prefs"), dict) else None
        ),
        media_expires_at=expires_at,
        payload=payload or None,
    )
