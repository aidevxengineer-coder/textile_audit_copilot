from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


rate_limiter = SlidingWindowRateLimiter()


def normalized_origin(value: str) -> str:
    return value.rstrip("/")


def origin_allowed(origin: str | None, allowed_origins: set[str]) -> bool:
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and normalized_origin(origin) in allowed_origins


def require_rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    if not rate_limiter.allow(key, limit=limit, window_seconds=window_seconds):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests. Please try again later.")


def request_ip(request: Request) -> str:
    # Do not trust X-Forwarded-For here unless a deployment-level trusted proxy
    # strips and rewrites it. The direct peer address cannot be user-spoofed.
    return request.client.host if request.client else "unknown"
