from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import get_settings


def get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.file_encryption_key.encode("utf-8")
    if len(key) != 44:
        digest = hashlib.sha256(key).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_bytes(payload: bytes) -> bytes:
    return get_fernet().encrypt(payload)


def decrypt_bytes(payload: bytes) -> bytes:
    return get_fernet().decrypt(payload)


def encrypt_text(value: str) -> str:
    return encrypt_bytes(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str) -> str:
    return decrypt_bytes(value.encode("utf-8")).decode("utf-8")


def write_encrypted_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt_bytes(payload))


def read_encrypted_file(path: Path) -> bytes:
    return decrypt_bytes(path.read_bytes())
