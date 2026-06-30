"""安全相关：密码哈希 + JWT 签发 / 校验。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt 哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希。"""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    return pwd_context.verify(plain, hashed)


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str) -> str:
    """创建短期 access token。"""
    return _create_token(
        subject,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    """创建长期 refresh token。"""
    return _create_token(
        subject,
        "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


class TokenDecodeError(Exception):
    """JWT 解码失败。"""


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """解码并校验 JWT。

    Args:
        token: 待解码的 JWT 字符串
        expected_type: 若提供，校验 payload["type"] 是否匹配

    Raises:
        TokenDecodeError: 解码失败或 type 不匹配
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise TokenDecodeError(f"JWT 解码失败：{exc}") from exc

    if expected_type and payload.get("type") != expected_type:
        raise TokenDecodeError(
            f"token 类型不匹配：期望 {expected_type}，实际 {payload.get('type')}"
        )
    return payload
