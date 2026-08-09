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
from tests.support.credentials import TEST_SESSION_SECRET


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
            SESSION_SECRET=TEST_SESSION_SECRET,
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
    retry_after = int(limited.headers["retry-after"])
    assert limited.json() == {
        "detail": f"Too many avatar recovery attempts. Try again in {retry_after} seconds.",
        "code": "rate_limited",
        "retry_after": retry_after,
    }
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


def test_expiry_sweep_is_amortised_rather_than_per_request():
    """The sweep used to run on every single check.

    At the default cap that is a 10,000-entry pass over the expiry map,
    holding the lock, on the event loop, for every request that reaches the
    limiter.
    """
    now = [0.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    sweeps: list[float] = []
    original = limiter._expire_inactive_locked

    def counting(when: float) -> None:
        sweeps.append(when)
        original(when)

    limiter._expire_inactive_locked = counting  # type: ignore[method-assign]

    for index in range(500):
        limiter.check(f"key-{index}", 100, 60)
    assert len(sweeps) == 1, "the sweep is still running per request"

    # It must still run as the clock advances, or expired buckets leak.
    now[0] = limiter._SWEEP_INTERVAL_SECONDS
    limiter.check("later", 100, 60)
    assert len(sweeps) == 2


def test_decisions_are_correct_before_a_sweep_has_run():
    """Correctness comes from the per-bucket cutoff, not the sweep.

    This is what makes amortising it safe: `check` drops timestamps older
    than the window from the bucket it touches, so an unswept bucket still
    answers correctly.
    """
    now = [0.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    assert limiter.check("caller", 1, 10).allowed
    assert not limiter.check("caller", 1, 10).allowed

    # Past the window but inside the sweep interval, so no sweep intervenes.
    now[0] = 10.5
    limiter._next_sweep = 1e9
    assert limiter.check("caller", 1, 10).allowed, "stale timestamps were not discarded"


def test_eviction_removes_the_least_recently_used_key():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(max_keys=2, clock=lambda: now[0])
    limiter.check("first", 5, 600)
    limiter.check("second", 5, 600)
    # Touching "first" makes "second" the least recently used.
    limiter.check("first", 5, 600)
    limiter.check("third", 5, 600)

    assert limiter.active_bucket_count == 2
    # "first" was touched most recently, so it survived with both timestamps.
    assert not limiter.check("first", 1, 600).allowed
    # "second" was least recently used, so it was evicted and starts fresh.
    assert limiter.check("second", 1, 600).allowed


def test_zero_limit_is_rejected_instead_of_crashing_request_handling():
    with pytest.raises(ValueError, match="positive"):
        parse_rate("0 per minute")


@pytest.mark.parametrize(
    "field_name",
    [
        "RATE_LIMIT_PARTY_CREATION",
        "RATE_LIMIT_API_CALLS",
        "RATE_LIMIT_LOGIN",
        "RATE_LIMIT_AVATAR_RECOVERY",
        "RATE_LIMIT_CHAT",
        "RATE_LIMIT_SOCKET_CONNECTIONS",
    ],
)
def test_invalid_runtime_rate_limit_is_rejected(field_name: str):
    config = _config()
    previous = getattr(config, field_name)

    changed, rejected = config.update_runtime({field_name: "ten/minute"})

    assert changed == []
    assert rejected == [{"key": field_name, "reason": "Invalid rate limit: 'ten/minute'"}]
    assert getattr(config, field_name) == previous


def test_invalid_persisted_rate_limit_falls_back_to_default(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text('{"RATE_LIMIT_LOGIN": "ten/minute"}', encoding="utf-8")

    runtime = RuntimeConfig.from_file(path)

    assert runtime.RATE_LIMIT_LOGIN == RuntimeConfig().RATE_LIMIT_LOGIN


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
    retry_after = int(limited.headers["retry-after"])
    assert limited.json() == {
        "detail": f"Too many requests. Try again in {retry_after} seconds.",
        "code": "rate_limited",
        "retry_after": retry_after,
    }


def test_party_creation_uses_stricter_limit():
    app = _limited_app()

    @app.post("/api/party/create")
    def create():
        return {"ok": True}

    async def exercise() -> httpx.Response:
        async with asgi_client(app) as client:
            assert (await client.post("/api/party/create")).status_code == 200
            return await client.post("/api/party/create")

    limited = asyncio.run(exercise())
    retry_after = int(limited.headers["retry-after"])
    assert limited.json() == {
        "detail": f"Too many party creation attempts. Try again in {retry_after} seconds.",
        "code": "rate_limited",
        "retry_after": retry_after,
    }


def test_retry_after_never_exceeds_the_configured_window():
    """`int(...) + 1` overshot every non-integral remainder.

    A frozen clock is the only way to reach the divergence deterministically:
    with the bucket filled at t and the window untouched, the true wait is the
    whole window, so the reported delay must equal it and never exceed it.
    """
    limiter = SlidingWindowRateLimiter(clock=lambda: 1000.0)
    for _ in range(5):
        assert limiter.check("key", 5, 3).allowed

    decision = limiter.check("key", 5, 3)

    assert not decision.allowed
    assert decision.retry_after == 3


def test_retry_after_rounds_a_partial_second_up_not_to_zero():
    """Guard on the max(1) floor, which the ceil change must not remove."""
    now = [1000.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])
    assert limiter.check("key", 1, 3).allowed
    now[0] = 1002.5

    decision = limiter.check("key", 1, 3)

    assert not decision.allowed
    # 0.5s of window left: rounds up to 1, never down to 0, which would invite
    # an immediate retry that is refused again.
    assert decision.retry_after == 1


def test_429_names_the_bucket_it_was_refused_by_not_the_path():
    """A 429 must describe the limit that actually refused the request.

    `/api/party/{id}/join` has no bucket of its own; it shares the general
    `api` bucket with every other route. Deriving the label from the request
    path instead of the bucket reports a viewer's FIRST join as "too many
    join attempts" once unrelated traffic has drained that shared bucket --
    and IndexView polls `/api/party/list` every 5s through the same bucket,
    so the page the viewer joins from is what exhausts it.
    """
    app = _limited_app()

    @app.get("/api/party/list")
    def party_list():
        return {"ok": True}

    @app.post("/api/party/ABC123/join")
    def join():
        return {"ok": True}

    async def exercise() -> httpx.Response:
        async with asgi_client(app) as client:
            # Background polling drains the shared bucket. No joins yet.
            assert (await client.get("/api/party/list")).status_code == 200
            assert (await client.get("/api/party/list")).status_code == 200
            # The viewer's first and only join attempt.
            return await client.post("/api/party/ABC123/join")

    limited = asyncio.run(exercise())
    assert limited.status_code == 429
    retry_after = int(limited.headers["retry-after"])
    assert limited.json() == {
        "detail": f"Too many requests. Try again in {retry_after} seconds.",
        "code": "rate_limited",
        "retry_after": retry_after,
    }


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
