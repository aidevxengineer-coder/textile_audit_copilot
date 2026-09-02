from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from passlib.context import CryptContext

from app.config import get_settings


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SUSPICIOUS_PATTERN = re.compile(
    r"(\$\(|`.+`|;|&&|\|\||\b(rm|del|drop table|truncate|powershell|cmd /c)\b)",
    re.IGNORECASE,
)


def sanitize_text(value: str, *, allow_question_text: bool = False) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()
    cleaned = cleaned.replace("</", "").replace("<", "").replace(">", "")
    if not allow_question_text and SUSPICIOUS_PATTERN.search(cleaned):
        raise ValueError("Potentially unsafe input detected.")
    return cleaned


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    return create_token(subject, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(subject: str) -> str:
    settings = get_settings()
    return create_token(subject, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
