from __future__ import annotations

import io
import zipfile

import pytest

from app.core.deployment_security import SlidingWindowRateLimiter, origin_allowed
from app.services.upload_service import UploadService, UploadValidationError


def test_origin_allowlist_requires_exact_scheme_host_and_port() -> None:
    allowed = {"https://audit.example.com"}
    assert origin_allowed("https://audit.example.com", allowed)
    assert not origin_allowed("https://audit.example.com.attacker.test", allowed)
    assert not origin_allowed("http://audit.example.com", allowed)
    assert not origin_allowed(None, allowed)


def test_sliding_window_rate_limiter_rejects_excess() -> None:
    limiter = SlidingWindowRateLimiter()
    assert limiter.allow("login:test", limit=2, window_seconds=60)
    assert limiter.allow("login:test", limit=2, window_seconds=60)
    assert not limiter.allow("login:test", limit=2, window_seconds=60)


def test_office_zip_bomb_is_rejected() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "A" * 2_000_000)

    with pytest.raises(UploadValidationError, match="compression ratio"):
        UploadService.validate_office_archive(payload.getvalue())


def test_office_archive_path_traversal_is_rejected() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../outside.xml", "unsafe")

    with pytest.raises(UploadValidationError, match="unsafe archive path"):
        UploadService.validate_office_archive(payload.getvalue())
