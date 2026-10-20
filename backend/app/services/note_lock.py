"""笔记密码锁：密码哈希与短期解锁令牌。

单用户本地应用没有账号体系，笔记锁用于「防止他人随手打开」：
- 密码只保存 PBKDF2-HMAC-SHA256 哈希，永不回传；
- 解锁成功后签发短期 HMAC 令牌，前端放在 ``X-Note-Token`` 请求头中；
- 令牌绑定当前密码盐值，改密 / 移除锁后旧令牌立即失效。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid

from app.config import settings

PBKDF2_ITERATIONS = 240_000
UNLOCK_TTL_SECONDS = 2 * 60 * 60


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return digest.hex()


def verify_password(note, password: str) -> bool:
    if not note.lock_hash or not note.lock_salt:
        return False
    candidate = hash_password(password, note.lock_salt)
    return hmac.compare_digest(candidate, note.lock_hash)


def _fingerprint(note) -> str:
    raw = f"{note.id}:{note.lock_salt}:{note.lock_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def issue_unlock_token(note, ttl: int = UNLOCK_TTL_SECONDS) -> tuple[str, int]:
    """签发解锁令牌，返回 (token, 过期时间戳)。"""
    expires_at = int(time.time()) + max(60, ttl)
    payload = f"{note.id}.{_fingerprint(note)}.{expires_at}"
    signature = hmac.new(
        settings.fernet_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    token = base64.urlsafe_b64encode(f"{payload}.{signature}".encode("utf-8")).decode()
    return token, expires_at


def token_is_valid(note, token: str | None) -> bool:
    if not token or not note.lock_hash:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        note_id, fingerprint, expires_raw, signature = raw.rsplit(".", 3)
        expires_at = int(expires_raw)
    except (ValueError, UnicodeDecodeError):
        return False
    if expires_at < int(time.time()):
        return False
    if note_id != str(note.id) or fingerprint != _fingerprint(note):
        return False
    payload = f"{note_id}.{fingerprint}.{expires_at}"
    expected = hmac.new(
        settings.fernet_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return hmac.compare_digest(signature, expected)


def is_locked(note) -> bool:
    return bool(note.lock_hash and note.lock_salt)


def lock_fingerprint(note) -> str:
    """给索引 / 缓存层使用的锁状态指纹。"""
    return _fingerprint(note) if is_locked(note) else ""


__all__ = [
    "UNLOCK_TTL_SECONDS",
    "hash_password",
    "is_locked",
    "issue_unlock_token",
    "lock_fingerprint",
    "new_salt",
    "token_is_valid",
    "verify_password",
]
