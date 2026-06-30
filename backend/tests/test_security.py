"""core.security / core.encryption 单测。"""

from __future__ import annotations

import pytest

from app.core.encryption import EncryptionError, decrypt, encrypt
from app.core.security import (
    TokenDecodeError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip() -> None:
    token = create_access_token("user-uuid")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-uuid"
    assert payload["type"] == "access"


def test_refresh_token_type_mismatch() -> None:
    access = create_access_token("u")
    with pytest.raises(TokenDecodeError):
        decode_token(access, expected_type="refresh")


def test_invalid_token() -> None:
    with pytest.raises(TokenDecodeError):
        decode_token("not.a.jwt")


def test_fernet_encrypt_decrypt() -> None:
    token = encrypt("sk-secret-key")
    assert token != "sk-secret-key"
    assert decrypt(token) == "sk-secret-key"


def test_fernet_decrypt_invalid() -> None:
    with pytest.raises(EncryptionError):
        decrypt("not-a-fernet-token")


def test_refresh_token_created() -> None:
    token = create_refresh_token("u1")
    payload = decode_token(token, expected_type="refresh")
    assert payload["sub"] == "u1"
    assert payload["type"] == "refresh"
