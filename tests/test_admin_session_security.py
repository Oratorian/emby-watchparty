import asyncio
import base64
import json
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from itsdangerous import TimestampSigner

from backend.app import create_app
from backend.src.admin_session_store import AdminSessionStore
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.domain import Participant
from backend.src.socket_handlers.connection import _decode_session
from tests.support.asgi import asgi_client
from tests.support.credentials import (
    LEGACY_COOKIE_ADMIN_TOKEN,
    REVOKED_ACCESS_TOKEN,
    TEST_SESSION_SECRET,
)


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
            MEDIA_SERVER_TYPE="emby",
            MEDIA_SERVER_URL="http://emby.test",
            MEDIA_SERVER_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
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


def test_failed_config_save_does_not_enable_static_session_in_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed disk write must not leave runtime config partially applied.

    Otherwise the index redirects to the configured static party even though
    PartyManager never created it, producing ``Party not found: PARTY`` after
    refresh.
    """

    def fail_save(_runtime: RuntimeConfig) -> None:
        raise OSError("config volume is read-only")

    monkeypatch.setattr(RuntimeConfig, "save", fail_save)

    async def exercise() -> None:
        application = _application(tmp_path)
        async with asgi_client(application) as client:
            assert (await _login(client)).json()["success"] is True

            saved = await client.put(
                "/api/admin/config",
                json={"STATIC_SESSION_ENABLED": True, "STATIC_SESSION_ID": "PARTY"},
            )

            assert saved.json()["success"] is False
            assert (await client.get("/api/party/static-session")).json() == {"party_id": None}
            assert application.state.party_manager.get("PARTY") is None

    asyncio.run(exercise())


def test_enabling_static_session_creates_static_party(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(RuntimeConfig, "save", lambda _runtime: None)

    async def exercise() -> None:
        application = _application(tmp_path)
        async with asgi_client(application) as client:
            assert (await _login(client)).json()["success"] is True

            saved = await client.put(
                "/api/admin/config",
                json={"STATIC_SESSION_ENABLED": True, "STATIC_SESSION_ID": "PARTY"},
            )

            assert saved.json()["success"] is True
            assert (await client.get("/api/party/static-session")).json() == {"party_id": "PARTY"}
            assert application.state.party_manager.get("PARTY") is not None

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


def test_session_cookie_lifetime_follows_session_expiry(tmp_path: Path) -> None:
    """`.env.example` calls SESSION_EXPIRY the session cookie lifetime.

    It was hardcoded to 14 days, so the setting governed only the admin
    store's TTL and the cookie outlived the admin session by thirteen days
    at the shipped defaults.
    """

    async def exercise() -> None:
        async with asgi_client(_application(tmp_path, session_expiry=3600)) as client:
            response = await _login(client)
            assert response.status_code == 200
            cookie = response.headers["set-cookie"]
            assert "ewp_session=" in cookie
            assert "Max-Age=3600" in cookie, f"cookie ignores SESSION_EXPIRY: {cookie}"

    asyncio.run(exercise())


def test_socket_handshake_expires_cookies_on_the_same_schedule_as_http() -> None:
    """The socket decoder must not outlive the HTTP one.

    connection.py hardcoded a 14-day max age with a comment requiring it to
    stay in sync with SessionMiddleware. Once the cookie began honouring
    SESSION_EXPIRY, that constant would have let the socket handshake accept
    a session every HTTP route already treated as expired, which is the
    fix-one-path-not-its-twin shape that reopened #48 and #52.
    """
    signer = TimestampSigner(TEST_SESSION_SECRET)
    payload = base64.b64encode(json.dumps({"party_id": "ABCDE"}).encode())
    environ = {"HTTP_COOKIE": f"ewp_session={signer.sign(payload).decode()}"}

    # Fresh cookie, well inside any window.
    assert _decode_session(environ, TEST_SESSION_SECRET, 3600) is not None

    # A window this session is already past. The handshake must refuse it
    # rather than fall back to a longer built-in lifetime.
    assert _decode_session(environ, TEST_SESSION_SECRET, -1) is None


def test_admin_session_ttl_renews_while_in_use() -> None:
    """The TTL is an idle timeout, not an absolute one.

    Without renewal a host who logged in 24 hours earlier lost admin
    controls mid-session, while the party cookie kept working, so nothing
    on screen explained why the controls had gone.
    """
    clock = [1000.0]
    store = AdminSessionStore(ttl_seconds=100, clock=lambda: clock[0])
    handle = store.create("Alice", "token", "user-1", is_admin=True)

    clock[0] = 1090.0  # 90s in, inside the window
    assert store.get(handle) is not None

    clock[0] = 1180.0  # 180s from login, but only 90s since it was last used
    assert store.get(handle) is not None, "an in-use session expired anyway"

    clock[0] = 1400.0  # 220s idle, well past the window
    assert store.get(handle) is None, "an idle session outlived its TTL"


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
            retry_after = int(limited.headers["retry-after"])
            assert limited.json() == {
                "detail": f"Too many login attempts. Try again in {retry_after} seconds.",
                "code": "rate_limited",
                "retry_after": retry_after,
            }
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


def test_disconnected_participant_can_reclaim_identity(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = _application(tmp_path)
        async with asgi_client(app) as creator:
            party_id = (await creator.post("/api/party/create", json={})).json()["party_id"]
            party = app.state.party_manager.get(party_id)
            party.participants["returning-client"] = Participant(
                client_id="returning-client",
                username="Returning",
            )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as returning:
                joined = await returning.post(
                    f"/api/party/{party_id}/join",
                    json={"client_id": "returning-client", "display_name": "Returning"},
                )

            assert joined.json()["success"] is True

    asyncio.run(exercise())


def test_departed_host_can_rejoin_their_own_party(tmp_path: Path) -> None:
    """A host who leaves during playback must not be locked out of their party.

    `host_client_id` is deliberately retained through PLAYING-ONLY so the
    in-flight stream survives, and `/api/party/leave` wipes the session
    including `host_session_grant`. Together those made the join gate
    refuse the genuine host on return: the identity reads as reserved and
    the proof of ownership has just been discarded.

    That is unrecoverable rather than merely annoying. `/api/auth/login`
    requires a bound party, which only a successful join provides, and
    `video_ended` / `stop_video` are both gated to the selector, who is
    the locked-out host. Nobody left in the party can end the video, so
    the party stays bricked until it dissolves.
    """

    async def exercise() -> None:
        app = _application(tmp_path)
        async with asgi_client(app) as host:
            party_id = (await host.post("/api/party/create", json={})).json()["party_id"]
            await host.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Alice"},
            )
            assert (
                await host.post(
                    "/api/auth/login", json={"username": "Alice", "password": "password"}
                )
            ).json()["is_admin"] is True

            party = app.state.party_manager.get(party_id)
            assert party.host_client_id == "host-client"

            # The host leaves. Playback is still running, so the party
            # keeps host_client_id; the session, and with it the grant,
            # is discarded.
            assert (await host.post("/api/party/leave")).json()["success"] is True
            assert party.host_client_id == "host-client"

            # They click the party link again, from the same browser.
            rejoined = await host.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Alice"},
            )
            assert rejoined.json()["success"] is True, rejoined.json().get("message")

    asyncio.run(exercise())


def test_departed_host_identity_still_needs_the_grant(tmp_path: Path) -> None:
    """Letting the host back in must not let anyone else in behind them.

    The rejoin fix accepts `host_session_grant` on its own, without a
    bound session. This pins the other half: after the host leaves, their
    `client_id` is still reserved against everyone who cannot produce
    that grant, including someone holding a perfectly valid session for
    the same party.
    """

    async def exercise() -> None:
        app = _application(tmp_path)
        async with (
            asgi_client(app) as host,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as attacker,
        ):
            party_id = (await host.post("/api/party/create", json={})).json()["party_id"]
            await host.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Alice"},
            )
            await host.post("/api/auth/login", json={"username": "Alice", "password": "password"})
            assert (await host.post("/api/party/leave")).json()["success"] is True

            # A real member of the same party, with a real session.
            assert (
                await attacker.post(
                    f"/api/party/{party_id}/join",
                    json={"client_id": "mallory-client", "display_name": "Mallory"},
                )
            ).json()["success"] is True

            # host_client_id is broadcast in host_changed, so treat it as public.
            claimed = await attacker.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Mallory"},
            )
            assert claimed.json()["success"] is False
            assert (await attacker.get("/api/admin/config")).json() == {
                "error": "Not authenticated"
            }

            # The genuine host, still holding the grant, gets back in.
            assert (
                await host.post(
                    f"/api/party/{party_id}/join",
                    json={"client_id": "host-client", "display_name": "Alice"},
                )
            ).json()["success"] is True

    asyncio.run(exercise())


def test_legacy_cookie_credentials_age_out_without_an_admin_login(tmp_path: Path) -> None:
    """Scrubbing must not depend on the user ever logging in as admin again.

    2.0.2 wrote a raw Emby admin token into the signed cookie. Starlette
    re-serialises the whole session dict on any modified response, so an
    ordinary party join re-signs the surviving legacy key with a fresh
    Max-Age: routine use renewed the leaked credential indefinitely rather
    than ageing it out. Someone who upgrades and simply keeps watching
    would never have triggered the login or logout paths.

    `require_party_session` now scrubs before it validates, so even a
    request that goes on to fail authorisation re-issues a cleaned cookie.
    """

    async def exercise() -> None:
        app = _application(tmp_path)

        async def seed_legacy(request: Request):
            request.session["admin_emby_token"] = LEGACY_COOKIE_ADMIN_TOKEN
            request.session["admin_emby_user_id"] = "legacy-user"
            return {"success": True}

        app.add_api_route("/_test/seed-legacy", seed_legacy, methods=["POST"])

        async with asgi_client(app) as client:
            await client.post("/_test/seed-legacy")
            seeded = base64.b64decode(client.cookies.get("ewp_session").split(".", 1)[0])
            assert LEGACY_COOKIE_ADMIN_TOKEN.encode() in seeded

            # No admin login, no logout. Just a party-gated route, which is
            # what ordinary use touches. It 401s for want of a party, and
            # that is the point: the scrub runs before the check.
            denied = await client.get("/hls/movie-1/master.m3u8")
            assert denied.status_code in {401, 404}

            remaining = client.cookies.get("ewp_session")
            if remaining is not None:
                decoded = base64.b64decode(remaining.split(".", 1)[0])
                assert LEGACY_COOKIE_ADMIN_TOKEN.encode() not in decoded, (
                    "legacy credential survived"
                )
                assert b"admin_emby_user_id" not in decoded

    asyncio.run(exercise())


def test_admin_login_and_logout_scrub_legacy_cookie_credentials(tmp_path: Path) -> None:
    async def exercise() -> None:
        app = _application(tmp_path)
        legacy_keys = {
            "admin_emby_token",
            "admin_emby_user_id",
            "admin_emby_is_admin",
            "admin_authenticated",
            "admin_username",
            "admin_session",
        }

        async def seed_legacy(request: Request):
            request.session.update(
                {
                    "admin_emby_token": "legacy-secret",
                    "admin_emby_user_id": "legacy-user",
                    "admin_emby_is_admin": True,
                    "admin_authenticated": True,
                    "admin_username": "Legacy",
                    "admin_session": "legacy-handle",
                }
            )
            return {"success": True}

        async def seed_invalid_stashed_admin(request: Request):
            await seed_legacy(request)
            request.session["admin_session_id"] = request.app.state.admin_session_store.create(
                username="Legacy",
                access_token=REVOKED_ACCESS_TOKEN,
                user_id="legacy-user",
                is_admin=True,
            )
            return {"success": True}

        app.add_api_route("/_test/seed-legacy", seed_legacy, methods=["POST"])
        app.add_api_route(
            "/_test/seed-invalid-stashed-admin",
            seed_invalid_stashed_admin,
            methods=["POST"],
        )

        def cookie_keys(client: httpx.AsyncClient) -> set[str]:
            cookie = client.cookies.get("ewp_session")
            if cookie is None:
                return set()
            payload = base64.b64decode(cookie.split(".", 1)[0])
            return set(json.loads(payload))

        async with asgi_client(app) as client:
            await client.post("/_test/seed-legacy")
            assert (await _login(client)).json()["success"] is True
            keys = cookie_keys(client)
            assert not legacy_keys & keys

            await client.post("/api/admin/logout")
            created = await client.post(
                "/api/party/create",
                json={"client_id": "legacy-client", "display_name": "Legacy"},
            )
            assert created.status_code == 200
            party_id = created.json()["party_id"]
            joined = await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "legacy-client", "display_name": "Legacy"},
            )
            assert joined.status_code == 200
            await client.post("/_test/seed-legacy")
            assert (await client.get("/api/libraries")).status_code == 423
            assert not legacy_keys & cookie_keys(client)

            await client.post("/_test/seed-invalid-stashed-admin")
            created = await client.post(
                "/api/party/create",
                json={"client_id": "new-client", "display_name": "Alice"},
            )
            assert created.status_code == 200
            keys = cookie_keys(client)
            assert not legacy_keys & keys

            await client.post("/_test/seed-legacy")
            await client.post("/api/admin/logout")
            keys = cookie_keys(client)
            assert not legacy_keys & keys

    asyncio.run(exercise())
