from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import httpx
import pytest
import uvicorn

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.fake_emby import FakeEmbyState, create_fake_emby_app


@dataclass(frozen=True)
class RunningFakeEmby:
    url: str
    state: FakeEmbyState


@dataclass(frozen=True)
class RunningWatchParty:
    url: str
    fake: RunningFakeEmby


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def fake_emby_server() -> RunningFakeEmby:
    port = _free_port()
    state = FakeEmbyState()
    server = uvicorn.Server(
        uvicorn.Config(
            create_fake_emby_app(state),
            host="127.0.0.1",
            port=port,
            log_level="error",
            proxy_headers=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/emby/System/Info/Public", timeout=0.1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.01)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("fake Emby did not start")
    state.requests.clear()
    try:
        yield RunningFakeEmby(url=url, state=state)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _run_watchparty(
    tmp_path,
    fake_emby_server: RunningFakeEmby,
    *,
    hls_token_validation: bool,
):
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL=fake_emby_server.url,
            EMBY_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET="test-session-secret-with-at-least-32-characters",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=hls_token_validation,
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    port = _free_port()
    application = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="127.0.0.1",
            port=port,
            log_level="error",
            proxy_headers=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            if httpx.get(f"{url}/api/health", timeout=0.1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.01)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("watch-party test server did not start")

    try:
        yield RunningWatchParty(url=url, fake=fake_emby_server)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture
def live_watchparty(tmp_path, fake_emby_server: RunningFakeEmby) -> RunningWatchParty:
    yield from _run_watchparty(
        tmp_path,
        fake_emby_server,
        hls_token_validation=True,
    )


@pytest.fixture
def live_watchparty_hls_disabled(
    tmp_path, fake_emby_server: RunningFakeEmby
) -> RunningWatchParty:
    yield from _run_watchparty(
        tmp_path,
        fake_emby_server,
        hls_token_validation=False,
    )
