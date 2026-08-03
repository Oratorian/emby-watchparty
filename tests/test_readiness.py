import asyncio
from pathlib import Path

import httpx

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET


def test_ready_reports_named_checks_through_running_app(live_watchparty) -> None:
    response = httpx.get(f"{live_watchparty.url}/api/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"config": True, "storage": True, "emby": True},
    }


def test_not_ready_when_emby_api_key_is_missing(
    tmp_path: Path,
    fake_emby_server,
) -> None:
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL=fake_emby_server.url,
            EMBY_API_KEY="",
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
