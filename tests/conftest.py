from __future__ import annotations

from dataclasses import dataclass
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from tests.support.fake_emby import FakeEmbyState, create_fake_emby_app


@dataclass(frozen=True)
class RunningFakeEmby:
    url: str
    state: FakeEmbyState


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
