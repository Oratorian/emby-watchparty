import asyncio
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.src.avatar_store import AvatarStore
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.dependencies import get_avatar_store, get_logger
from backend.src.rate_limit import (
    RateLimitMiddleware,
    SlidingWindowRateLimiter,
    parse_rate,
)
from backend.src.routers import avatar
from tests.support.asgi import asgi_client


def _config(*, prefix: str = "") -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX=prefix,
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET="test-session-secret-with-at-least-32-characters",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(
            ENABLE_RATE_LIMITING=True,
            RATE_LIMIT_API_CALLS="2 per minute",
            RATE_LIMIT_PARTY_CREATION="1 per hour",
        ),
    )


def _limited_app(prefix: str = "") -> FastAPI:
    app = FastAPI()
    app.state.config = _config(prefix=prefix)
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.add_middleware(RateLimitMiddleware)
    return app


def test_avatar_recovery_uses_shared_limiter_and_retry_after(tmp_path: Path):
    app = FastAPI()
    app.state.config = _config()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.include_router(avatar.router)
    store = AvatarStore(
        tmp_path / "avatars.db",
        tmp_path / "avatars",
        logging.getLogger("test-rate-limit"),
    )
    app.dependency_overrides[get_avatar_store] = lambda: store
    app.dependency_overrides[get_logger] = lambda: logging.getLogger("test-rate-limit")

    async def exercise() -> httpx.Response:
        async with asgi_client(app) as client:
            for _ in range(10):
                response = await client.post("/api/avatar/recover", json={"code": "bad"})
                assert response.status_code == 200
            return await client.post("/api/avatar/recover", json={"code": "bad"})

    limited = asyncio.run(exercise())
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert app.state.rate_limiter.active_bucket_count == 1


def test_inactive_buckets_expire_and_registry_stays_bounded():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(max_keys=2, clock=lambda: now[0])
    assert limiter.check("one", 1, 10).allowed
    assert limiter.check("two", 1, 10).allowed
    assert limiter.check("three", 1, 10).allowed
    assert limiter.active_bucket_count <= 2
    now[0] = 11.0
    assert limiter.check("four", 1, 10).allowed
    assert limiter.active_bucket_count == 1


def test_zero_limit_is_rejected_instead_of_crashing_request_handling():
    with pytest.raises(ValueError, match="positive"):
        parse_rate("0 per minute")


def test_general_api_limit_returns_429_with_retry_after():
    app = _limited_app()

    @app.get("/api/example")
    def example():
        return {"ok": True}

    async def exercise() -> httpx.Response:
        async with asgi_client(app) as client:
            assert (await client.get("/api/example")).status_code == 200
            assert (await client.get("/api/example")).status_code == 200
            return await client.get("/api/example")

    limited = asyncio.run(exercise())
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_party_creation_uses_stricter_limit():
    app = _limited_app()

    @app.post("/api/party/create")
    def create():
        return {"ok": True}

    async def exercise() -> None:
        async with asgi_client(app) as client:
            assert (await client.post("/api/party/create")).status_code == 200
            assert (await client.post("/api/party/create")).status_code == 429

    asyncio.run(exercise())


def test_rate_limit_honors_application_prefix():
    app = _limited_app("/watchparty")

    @app.get("/watchparty/api/example")
    def example():
        return {"ok": True}

    async def exercise() -> None:
        async with asgi_client(app) as client:
            assert (await client.get("/watchparty/api/example")).status_code == 200
            assert (await client.get("/watchparty/api/example")).status_code == 200
            assert (await client.get("/watchparty/api/example")).status_code == 429

    asyncio.run(exercise())


def test_avatar_recovery_honors_master_rate_limit_toggle(tmp_path: Path):
    app = FastAPI()
    app.state.config = _config()
    app.state.config._runtime.ENABLE_RATE_LIMITING = False
    app.state.config._runtime.RATE_LIMIT_AVATAR_RECOVERY = "1 per hour"
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.include_router(avatar.router)
    store = AvatarStore(
        tmp_path / "avatars.db",
        tmp_path / "avatars",
        logging.getLogger("test-rate-limit-disabled"),
    )
    app.dependency_overrides[get_avatar_store] = lambda: store
    app.dependency_overrides[get_logger] = lambda: logging.getLogger("test-rate-limit-disabled")

    async def exercise() -> None:
        async with asgi_client(app) as client:
            for _ in range(3):
                assert (
                    await client.post("/api/avatar/recover", json={"code": "bad"})
                ).status_code == 200

    asyncio.run(exercise())
    assert app.state.rate_limiter.active_bucket_count == 0
