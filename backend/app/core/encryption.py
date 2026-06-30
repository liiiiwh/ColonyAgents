"""对称加密工具：用于加密 LLM Provider API Key 等敏感字段。

使用 Fernet（AES-128-CBC + HMAC-SHA256）。
密钥通过环境变量 `ENCRYPTION_KEY` 提供，须为 base64 编码的 32 字节密钥。

生成密钥示例：
    >>> from cryptography.fernet import Fernet
    >>> Fernet.generate_key().decode()
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class EncryptionError(RuntimeError):
    """加密 / 解密失败。"""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    if not settings.ENCRYPTION_KEY:
        raise EncryptionError(
            "ENCRYPTION_KEY 未配置。请设置环境变量后重启服务。"
            "可用 `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` 生成。"
        )
    try:
        return Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - 仅配置错误时触发
        raise EncryptionError(f"ENCRYPTION_KEY 非法：{exc}") from exc


def encrypt(plaintext: str) -> str:
    """加密明文，返回 base64 token 字符串。"""
    if plaintext is None:
        raise ValueError("encrypt plaintext 不能为 None")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """解密 token，返回原始明文。"""
    if not token:
        raise ValueError("decrypt token 不能为空")
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError("解密失败：token 无效或密钥错误") from exc
