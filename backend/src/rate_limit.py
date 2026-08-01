"""Bounded in-memory rate limiting for single-process deployments."""

from collections import deque
from dataclasses import dataclass
import re
import threading
import time
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from backend.src.client_ip import request_client_ip


_PERIOD_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 60 * 60,
    "day": 24 * 60 * 60,
}


def parse_rate(spec: str) -> tuple[int, int]:
    match = re.fullmatch(
        r"\s*(\d+)\s+per(?:\s+(\d+))?\s+(second|minute|hour|day)s?\s*",
        spec,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Invalid rate limit: {spec!r}")
    limit = int(match.group(1))
    if limit <= 0:
        raise ValueError("Rate limit must be positive")
    multiplier = int(match.group(2) or "1")
    if multiplier <= 0:
        raise ValueError("Rate limit window must be positive")
    return limit, multiplier * _PERIOD_SECONDS[match.group(3).lower()]


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


class SlidingWindowRateLimiter:
    def __init__(self, max_keys: int = 10_000,
                 clock: Callable[[], float] = time.monotonic):
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, deque[float]] = {}
        self._last_seen: dict[str, float] = {}
        self._expires_at: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def active_bucket_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            self._expire_inactive_locked(now)
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            self._last_seen[key] = now
            self._expires_at[key] = now + window_seconds
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
                return RateLimitDecision(False, retry_after)
            bucket.append(now)
            self._evict_if_needed_locked()
            return RateLimitDecision(True)

    def clear(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)
            self._last_seen.pop(key, None)
            self._expires_at.pop(key, None)

    def _expire_inactive_locked(self, now: float) -> None:
        expired = [key for key, expiry in self._expires_at.items() if expiry <= now]
        for key in expired:
            self._buckets.pop(key, None)
            self._last_seen.pop(key, None)
            self._expires_at.pop(key, None)

    def _evict_if_needed_locked(self) -> None:
        while len(self._buckets) > self._max_keys:
            oldest = min(self._last_seen, key=lambda key: self._last_seen[key])
            self._buckets.pop(oldest, None)
            self._last_seen.pop(oldest, None)
            self._expires_at.pop(oldest, None)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request,
        call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        config = request.app.state.config
        api_root = f"{config.APP_PREFIX}/api"
        if not path.startswith(f"{api_root}/") or path in {
            f"{api_root}/health", f"{api_root}/ready",
        }:
            return await call_next(request)

        if not config.ENABLE_RATE_LIMITING:
            return await call_next(request)

        is_party_create = path == f"{api_root}/party/create" and request.method == "POST"
        spec = (
            config.RATE_LIMIT_PARTY_CREATION
            if is_party_create
            else config.RATE_LIMIT_API_CALLS
        )
        try:
            limit, window = parse_rate(spec)
        except ValueError:
            return await call_next(request)

        client_ip = request_client_ip(request, config.TRUSTED_PROXY_CIDRS)
        scope = "party-create" if is_party_create else "api"
        decision = request.app.state.rate_limiter.check(
            f"{scope}:{client_ip}", limit, window
        )
        if not decision.allowed:
            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(decision.retry_after)},
            )
        return await call_next(request)
