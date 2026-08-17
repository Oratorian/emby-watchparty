import asyncio
import json
from pathlib import Path

import httpx

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET
from tests.support.fake_jellyfin import create_fake_jellyfin_app


def test_ready_reports_named_checks_through_running_app(live_watchparty) -> None:
    response = httpx.get(f"{live_watchparty.url}/api/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "config": True,
            "storage": True,
            "media_server_reachable": True,
            "media_server_credentials": True,
            "emby": True,
        },
    }


def test_ready_reports_neutral_jellyfin_checks(tmp_path: Path) -> None:
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="jellyfin",
            MEDIA_SERVER_URL="http://jellyfin.test",
            MEDIA_SERVER_API_KEY="jellyfin-api-key",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    app = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_jellyfin_app()),
    )

    async def exercise() -> httpx.Response:
        async with asgi_client(app) as client:
            return await client.get("/api/ready")

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "config": True,
            "storage": True,
            "media_server_reachable": True,
            "media_server_credentials": True,
        },
    }


def test_not_ready_when_the_api_key_is_missing(
    tmp_path: Path,
    fake_emby_server,
) -> None:
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="emby",
            MEDIA_SERVER_URL=fake_emby_server.url,
            MEDIA_SERVER_API_KEY="",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    app = create_app(config=config, project_root=tmp_path, enable_update_check=False)

    async def exercise() -> httpx.Response:
        async with asgi_client(app) as client:
            return await client.get("/api/ready")

    response = asyncio.run(exercise())

    assert response.status_code == 503
    assert response.json()["checks"]["config"] is False


def test_the_emby_compat_key_agrees_with_the_overall_status() -> None:
    """A monitor reading only `checks.emby` must not be told the opposite.

    The key aliased `reachable` alone while readiness also requires
    credentials_valid, so a reachable server with a rejected API key answered
    503 not_ready with "emby": true inside it.
    """
    from types import SimpleNamespace

    from backend.src.routers import health

    class _Provider:
        async def readiness(self):
            return SimpleNamespace(reachable=True, credentials_valid=False)

    class _AvatarStore:
        def readiness_check(self) -> bool:
            return True

    config = SimpleNamespace(
        MEDIA_SERVER_URL="http://emby.test",
        MEDIA_SERVER_API_KEY="key",
        MEDIA_SERVER_TYPE="emby",
    )

    response = asyncio.run(
        health.ready(
            config=config,
            media_server=_Provider(),
            avatar_store=_AvatarStore(),
        )
    )
    body = json.loads(response.body)

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["emby"] is False, (
        "the compat key claimed the media server was fine inside a not_ready body"
    )
