import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.credentials import TEST_SESSION_SECRET


class ClosingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.closed = False

    async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ServerName": "Fake Emby"})

    async def aclose(self) -> None:
        self.closed = True


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
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


async def _start_with_invalid_storage(root_file: Path) -> ClosingTransport:
    transport = ClosingTransport()
    app = create_app(
        config=_config(),
        project_root=root_file,
        enable_update_check=False,
        http_transport=transport,
    )
    with pytest.raises(OSError, match=r"not-a-directory|File exists|Invalid argument"):
        async with app.router.lifespan_context(app):
            pass
    return transport


def test_partial_startup_closes_lifespan_http_transport(tmp_path: Path) -> None:
    root_file = tmp_path / "not-a-directory"
    root_file.write_text("occupied", encoding="utf-8")

    transport = asyncio.run(_start_with_invalid_storage(root_file))

    assert transport.closed is True


def test_failed_startup_keeps_stale_setup_artifacts_for_recovery(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "avatars.db").mkdir()
    stale_paths = [data / "bootstrap.json", data / "setup-token"]
    for path in stale_paths:
        path.write_text("recoverable", encoding="utf-8")

    app = create_app(
        config=_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    async def fail_startup() -> None:
        with pytest.raises(sqlite3.OperationalError):
            async with app.router.lifespan_context(app):
                pass

    asyncio.run(fail_startup())

    assert all(path.read_text(encoding="utf-8") == "recoverable" for path in stale_paths)
