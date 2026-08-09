import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET


class SensitiveFailureTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        password = body["Pw"]
        raise httpx.ConnectError(
            f"upstream rejected password={password}&api_key=super-secret-api-key",
            request=request,
        )


def _config() -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="super-secret-api-key",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


async def _login_with_sensitive_upstream_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(
        config=_config(),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=SensitiveFailureTransport(),
    )
    with caplog.at_level(logging.DEBUG):
        async with asgi_client(app) as client:
            response = await client.post(
                "/api/admin/login",
                json={"username": "admin", "password": "submitted-password"},
            )
    assert response.status_code == 200
    assert response.json()["success"] is False


def test_admin_login_logs_redact_upstream_credentials(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_login_with_sensitive_upstream_failure(tmp_path, caplog))

    assert "submitted-password" not in caplog.text
    assert "super-secret-api-key" not in caplog.text
    assert "ConnectError" in caplog.text


def test_party_login_reports_unreachable_emby_without_blending_with_credentials(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        app = create_app(
            config=_config(),
            project_root=tmp_path,
            enable_update_check=False,
            http_transport=SensitiveFailureTransport(),
        )
        async with asgi_client(app) as client:
            party_id = (await client.post("/api/party/create", json={})).json()["party_id"]
            await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "unreachable-emby", "display_name": "Operator"},
            )

            response = await client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "submitted-password"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "message": "Emby server unavailable; ask the operator to verify EMBY_SERVER_URL",
            "username": None,
            "is_admin": False,
            "is_host": False,
            "host_username": None,
        }

    asyncio.run(exercise())


def test_uvicorn_access_logger_is_silenced_for_every_entrypoint(tmp_path: Path) -> None:
    """uvicorn's own access logger must never run.

    It writes the full request line at INFO, query string included, and
    every HLS URL carries `?token=<hls token>`, so an enabled access log
    publishes a working stream credential on each playlist and segment
    request.

    Asserted on the logger rather than on `uvicorn.run(access_log=False)`
    because that argument only covers `python -m backend.app`. Starting
    through the ASGI target instead, `uvicorn backend.app:app --reload`,
    never reaches main() and leaked until this moved into the shared
    logging setup.
    """
    access = logging.getLogger("uvicorn.access")
    access.disabled = False

    app = create_app(config=_config(), project_root=tmp_path, enable_update_check=False)

    async def exercise() -> None:
        async with asgi_client(app):
            assert access.disabled is True

    asyncio.run(exercise())
