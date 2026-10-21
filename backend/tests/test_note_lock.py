"""笔记密码锁与正文加密的纯逻辑测试。"""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace

import pytest

from app.services import note_lock


def make_note(*, encrypted: bool = False, body: str = "秘密正文", password: str = "test1234"):
    note = SimpleNamespace(
        id=uuid.uuid4(),
        lock_hash=None,
        lock_salt=None,
        lock_hint=None,
        lock_encrypted=False,
        lock_enc_salt=None,
        body_md=body,
        body_enc=None,
    )
    note.lock_salt = note_lock.new_salt()
    note.lock_hash = note_lock.hash_password(password, note.lock_salt)
    if encrypted:
        note.lock_enc_salt = note_lock.new_salt()
        note.body_enc = note_lock.encrypt_body(password, note.lock_enc_salt, body)
        note.body_md = ""
        note.lock_encrypted = True
    return note


def test_password_hash_roundtrip():
    note = make_note(password="correct horse")
    assert note_lock.verify_password(note, "correct horse") is True
    assert note_lock.verify_password(note, "wrong password") is False
    assert note_lock.is_locked(note) is True


def test_encrypt_decrypt_body_roundtrip():
    salt = note_lock.new_salt()
    ciphertext = note_lock.encrypt_body("pw1234", salt, "机密内容 alpha")
    assert ciphertext != "机密内容 alpha"
    assert note_lock.decrypt_body("pw1234", salt, ciphertext) == "机密内容 alpha"
    with pytest.raises(note_lock.NoteEncryptionError):
        note_lock.decrypt_body("wrong", salt, ciphertext)


def test_unlock_token_roundtrip():
    note = make_note(encrypted=True)
    content_key = note_lock.derive_content_key("test1234", note.lock_enc_salt)
    token, expires_at = note_lock.issue_unlock_token(note, content_key=content_key)
    assert expires_at > 0
    assert note_lock.token_is_valid(note, token)
    assert note_lock.token_content_key(note, token) == content_key
    assert note_lock.note_body(note, token) == "秘密正文"


def test_token_invalid_after_password_change():
    note = make_note()
    token, _ = note_lock.issue_unlock_token(note)
    assert note_lock.token_is_valid(note, token)
    note.lock_salt = note_lock.new_salt()
    note.lock_hash = note_lock.hash_password("new-password", note.lock_salt)
    assert note_lock.token_is_valid(note, token) is False


def test_token_tamper_rejected():
    note = make_note()
    token, _ = note_lock.issue_unlock_token(note)
    raw = bytearray(base64.urlsafe_b64decode(token))
    raw[-1] = ord("A") if raw[-1] != ord("A") else ord("B")
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
    assert note_lock.token_is_valid(note, tampered) is False


def test_encrypted_body_not_exposed_without_token():
    note = make_note(encrypted=True)
    assert note_lock.is_encrypted(note) is True
    assert note_lock.note_body(note, None) == ""
    assert note_lock.note_body(note, "invalid-token") == ""
    token, _ = note_lock.issue_unlock_token(
        note, content_key=note_lock.derive_content_key("test1234", note.lock_enc_salt)
    )
    assert note_lock.note_body(note, token) == "秘密正文"


def test_token_does_not_carry_key_for_plain_lock():
    note = make_note(encrypted=False)
    token, _ = note_lock.issue_unlock_token(note)
    assert note_lock.token_is_valid(note, token)
    assert note_lock.token_content_key(note, token) is None
    assert note_lock.note_body(note, token) == "秘密正文"
