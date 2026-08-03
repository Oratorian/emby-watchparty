import asyncio
import socket
from pathlib import Path

import httpx
import socketio
import uvicorn

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.credentials import TEST_SESSION_SECRET


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


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def _exercise_last_user_leave(tmp_path: Path) -> None:
    port = _free_port()
    application = create_app(
        config=_config(),
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
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        base_url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base_url) as client:
            created = await client.post("/api/party/create", json={})
            party_id = created.json()["party_id"]
            joined = await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            assert joined.json()["success"] is True

            cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
            realtime = socketio.AsyncClient()
            await realtime.connect(base_url, headers={"Cookie": cookie})
            await realtime.emit(
                "join_party",
                {
                    "party_id": party_id,
                    "username": "Alice",
                    "client_id": "client-1",
                },
            )
            await asyncio.sleep(0.05)
            await realtime.emit("leave_party", {"party_id": party_id})
            await asyncio.sleep(0.05)

            exists = await client.get(f"/api/party/{party_id}/exists")
            assert exists.json() == {"exists": False}
            await realtime.disconnect()
    finally:
        server.should_exit = True
        await server_task


def test_last_user_leave_dissolves_dynamic_party(tmp_path: Path) -> None:
    asyncio.run(_exercise_last_user_leave(tmp_path))
