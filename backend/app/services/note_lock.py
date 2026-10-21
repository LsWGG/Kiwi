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

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

PBKDF2_ITERATIONS = 240_000
UNLOCK_TTL_SECONDS = 2 * 60 * 60


class NoteEncryptionError(Exception):
    """加密存储相关的可预期错误（密码不符 / 服务端密钥未配置）。"""


def _server_fernet() -> Fernet:
    key = settings.fernet_key
    if not key or key.startswith("change_me"):
        raise NoteEncryptionError(
            "未配置 KIWI_FERNET_KEY，无法启用笔记加密存储"
        )
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise NoteEncryptionError(f"KIWI_FERNET_KEY 非法：{e}") from e


def derive_content_key(password: str, salt: str) -> bytes:
    """从密码派生 Fernet 密钥（与解锁哈希使用不同的盐值）。"""
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(raw)


def encrypt_body(password: str, salt: str, body: str) -> str:
    return Fernet(derive_content_key(password, salt)).encrypt(body.encode("utf-8")).decode()


def decrypt_body(password: str, salt: str, token: str) -> str:
    try:
        return (
            Fernet(derive_content_key(password, salt))
            .decrypt(token.encode("ascii"))
            .decode("utf-8")
        )
    except (InvalidToken, ValueError) as e:
        raise NoteEncryptionError("密码无法解密正文（密码错误或数据损坏）") from e


def decrypt_with_key(key: bytes, token: str) -> str:
    try:
        return Fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        raise NoteEncryptionError("解锁令牌中的正文密钥无效") from e


def encrypt_with_key(key: bytes, body: str) -> str:
    return Fernet(key).encrypt(body.encode("utf-8")).decode()


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
    raw = (
        f"{note.id}:{note.lock_salt}:{note.lock_hash}:"
        f"{int(bool(getattr(note, 'lock_encrypted', False)))}:"
        f"{getattr(note, 'lock_enc_salt', '') or ''}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def issue_unlock_token(
    note, ttl: int = UNLOCK_TTL_SECONDS, content_key: bytes | None = None
) -> tuple[str, int]:
    """签发解锁令牌，返回 (token, 过期时间戳)。

    加密存储的笔记会把「正文密钥」用服务端 Fernet 密钥封装后放进令牌；
    这样数据库转储本身无法解密正文，而携带令牌的请求无需重新输入密码即可
    自动保存。服务端密钥与数据库应分开保管。
    """
    expires_at = int(time.time()) + max(60, ttl)
    key_token = "-"
    if content_key is not None:
        key_token = _server_fernet().encrypt(content_key).decode("ascii")
    payload = f"{note.id}.{_fingerprint(note)}.{expires_at}.{key_token}"
    signature = hmac.new(
        settings.fernet_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    token = base64.urlsafe_b64encode(f"{payload}.{signature}".encode("utf-8")).decode()
    return token, expires_at


def _parse_token(note, token: str | None) -> tuple[str, str] | None:
    if not token or not note.lock_hash:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        note_id, fingerprint, expires_raw, key_token, signature = raw.rsplit(".", 4)
        expires_at = int(expires_raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if expires_at < int(time.time()):
        return None
    if note_id != str(note.id) or fingerprint != _fingerprint(note):
        return None
    payload = f"{note_id}.{fingerprint}.{expires_at}.{key_token}"
    expected = hmac.new(
        settings.fernet_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        return None
    return key_token, payload


def token_is_valid(note, token: str | None) -> bool:
    return _parse_token(note, token) is not None


def token_content_key(note, token: str | None) -> bytes | None:
    """从令牌中取回正文密钥；未加密 / 令牌无效时返回 None。"""
    parsed = _parse_token(note, token)
    if parsed is None:
        return None
    key_token, _ = parsed
    if key_token == "-":
        return None
    try:
        return _server_fernet().decrypt(key_token.encode("ascii"))
    except (InvalidToken, NoteEncryptionError):
        return None


def note_body(note, token: str | None = None) -> str:
    """返回可展示的正文：加密笔记只在有效令牌下解密。"""
    if getattr(note, "lock_encrypted", False) and note.body_enc:
        key = token_content_key(note, token)
        if key is None:
            return ""
        try:
            return decrypt_with_key(key, note.body_enc)
        except NoteEncryptionError:
            return ""
    return note.body_md or ""


def is_locked(note) -> bool:
    return bool(note.lock_hash and note.lock_salt)


def is_encrypted(note) -> bool:
    return bool(getattr(note, "lock_encrypted", False) and note.body_enc)


def lock_fingerprint(note) -> str:
    """给索引 / 缓存层使用的锁状态指纹。"""
    return _fingerprint(note) if is_locked(note) else ""


__all__ = [
    "UNLOCK_TTL_SECONDS",
    "NoteEncryptionError",
    "decrypt_body",
    "decrypt_with_key",
    "derive_content_key",
    "encrypt_body",
    "encrypt_with_key",
    "hash_password",
    "is_encrypted",
    "is_locked",
    "issue_unlock_token",
    "lock_fingerprint",
    "new_salt",
    "note_body",
    "token_content_key",
    "token_is_valid",
    "verify_password",
]
