import asyncio
import base64
from pathlib import Path

import httpx
from fastapi import FastAPI

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from tests.support.asgi import asgi_client


def _config(
    *,
    session_expiry: int = 3600,
    login_rate: str = "10 per 15 minutes",
) -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=session_expiry,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET="test-session-secret-with-at-least-32-characters",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False, RATE_LIMIT_LOGIN=login_rate),
    )


def _fake_emby() -> FastAPI:
    app = FastAPI()

    @app.post("/emby/Users/AuthenticateByName")
    async def authenticate():
        return {
            "AccessToken": "secret-upstream-token",
            "User": {
                "Id": "admin-user",
                "Name": "Alice",
                "Policy": {"IsAdministrator": True},
            },
        }

    @app.post("/emby/Sessions/Capabilities/Full")
    async def capabilities():
        return {}

    return app


def _application(
    tmp_path: Path,
    *,
    session_expiry: int = 3600,
    login_rate: str = "10 per 15 minutes",
):
    return create_app(
        config=_config(session_expiry=session_expiry, login_rate=login_rate),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=_fake_emby()),
    )


async def _login(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post(
        "/api/admin/login",
        json={"username": "Alice", "password": "password"},
    )


def test_admin_login_keeps_emby_token_out_of_browser_cookie(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with asgi_client(_application(tmp_path)) as client:
            response = await _login(client)
            assert response.status_code == 200
            assert response.json() == {"success": True, "message": None}

            cookie = client.cookies.get("ewp_session")
            assert cookie is not None
            unsigned_payload = cookie.split(".", 1)[0]
            decoded = base64.b64decode(unsigned_payload).decode("utf-8")
            assert "secret-upstream-token" not in decoded
            config = await client.get("/api/admin/config")
            assert config.json()["LOG_LEVEL"] == "INFO"

    asyncio.run(exercise())


def test_admin_logout_revokes_server_side_session(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with asgi_client(_application(tmp_path)) as client:
            assert (await _login(client)).json()["success"] is True
            assert (await client.post("/api/admin/logout")).json()["success"] is True
            assert (await client.get("/api/admin/config")).json() == {"error": "Not authenticated"}

    asyncio.run(exercise())


def test_expired_admin_session_no_longer_grants_access(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with asgi_client(_application(tmp_path, session_expiry=0)) as client:
            assert (await _login(client)).json()["success"] is True
            assert (await client.get("/api/admin/config")).json() == {"error": "Not authenticated"}

    asyncio.run(exercise())


def test_process_restart_invalidates_admin_session(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with asgi_client(_application(tmp_path / "first")) as first:
            assert (await _login(first)).json()["success"] is True
            cookie = first.cookies.get("ewp_session")
            assert cookie is not None

        async with asgi_client(_application(tmp_path / "second")) as restarted:
            restarted.cookies.set("ewp_session", cookie)
            assert (await restarted.get("/api/admin/config")).json() == {
                "error": "Not authenticated"
            }

    asyncio.run(exercise())


def test_admin_login_limit_expires_and_returns_retry_after(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = _application(tmp_path, login_rate="1 per second")
        async with asgi_client(app) as client:
            assert (await _login(client)).status_code == 200
            limited = await _login(client)
            assert limited.status_code == 429
            assert int(limited.headers["retry-after"]) > 0
            await asyncio.sleep(1.05)
            assert (await _login(client)).status_code == 200

    asyncio.run(exercise())


def test_join_cannot_claim_existing_admin_host_identity(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = _application(tmp_path)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as host,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as attacker,
        ):
            created = await host.post("/api/party/create", json={})
            party_id = created.json()["party_id"]
            await host.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Alice"},
            )
            preclaimed = await attacker.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Mallory"},
            )
            assert preclaimed.json()["success"] is True
            login = await host.post(
                "/api/auth/login",
                json={"username": "Alice", "password": "password"},
            )
            assert login.json()["is_admin"] is True
            assert (await attacker.get("/api/admin/config")).json() == {
                "error": "Not authenticated"
            }
            assert (await attacker.get("/api/auth/status")).json()["is_host"] is False
            assert (await attacker.post("/api/auth/logout")).json()["message"] == "Not the host"

            claimed = await attacker.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Mallory"},
            )
            assert claimed.json()["success"] is False

    asyncio.run(exercise())
