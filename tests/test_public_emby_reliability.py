from pathlib import Path

import httpx
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig


def _config() -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET="test-session-secret-with-at-least-32-characters",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def test_readiness_retries_transient_emby_read_failures(tmp_path: Path) -> None:
    fake_emby = FastAPI()
    attempts = 0

    @fake_emby.get("/emby/System/Info/Public")
    async def public_info():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return Response(status_code=503)
        return {"ServerName": "Fake Emby"}

    application = create_app(
        config=_config(),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=fake_emby),
    )

    with TestClient(application) as client:
        response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert attempts == 3
