"""A development host refresh must preserve the socket's cookie proof."""

import asyncio
import base64
import json
import secrets
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from itsdangerous import TimestampSigner

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.dependencies import party_host_session_matches
from backend.src.socket_handlers.connection import _decode_session
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET
from tests.support.fake_emby import create_fake_emby_app


def _application(root: Path):
    return create_app(
        config=Config(
            EnvConfig(
                WATCH_PARTY_BIND="127.0.0.1",
                WATCH_PARTY_PORT=5000,
                APP_PREFIX="",
                SESSION_EXPIRY=3600,
                MEDIA_SERVER_TYPE="emby",
                MEDIA_SERVER_URL="http://emby.test",
                MEDIA_SERVER_API_KEY="test-key",
                APP_ENV="development",
                SESSION_SECRET=TEST_SESSION_SECRET,
                SESSION_COOKIE_SECURE=False,
                CORS_ALLOWED_ORIGINS=("*",),
                TRUSTED_PROXY_CIDRS=(),
            ),
            RuntimeConfig(LOG_TO_FILE=False, ENABLE_RATE_LIMITING=False),
            private_env={
                "EMBY_WATCHPARTY_X_DEV_HOST": "Alice:password",
                "EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK": "true",
            },
        ),
        project_root=root,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_emby_app()),
    )


async def _socket(application, engine_id: str, cookie: str | None):
    sio = application.state.sio
    sid = await sio.manager.connect(engine_id, "/")
    sio.environ[engine_id] = {"HTTP_COOKIE": f"ewp_session={cookie}"} if cookie else {}
    return sid


def _session(client: httpx.AsyncClient):
    return _decode_session(
        {"HTTP_COOKIE": f"ewp_session={client.cookies.get('ewp_session')}"},
        TEST_SESSION_SECRET,
        3600,
    )


def test_first_development_join_still_authenticates_and_grants_host(tmp_path, monkeypatch):
    application = _application(tmp_path)

    async def exercise():
        async with asgi_client(application) as client:
            authenticate = AsyncMock(wraps=application.state.media_server.authenticate_user)
            monkeypatch.setattr(application.state.media_server, "authenticate_user", authenticate)
            party_id = (await client.post("/api/party/create", json={})).json()["party_id"]
            result = await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Alice"},
            )

            assert result.json()["success"] is True
            assert result.json()["is_host"] is True
            assert result.json()["party_unlocked"] is True
            authenticate.assert_awaited_once_with("Alice", "password")
            status = await client.get("/api/v2/auth/status")
            assert status.json()["is_host"] is True
            assert application.state.party_manager.get(party_id).host_session_grant

    asyncio.run(exercise())


def test_host_refresh_during_grace_keeps_the_frozen_handshake_grant(tmp_path, monkeypatch):
    application = _application(tmp_path)

    async def exercise():
        async with asgi_client(application) as client:
            authenticate = AsyncMock(wraps=application.state.media_server.authenticate_user)
            monkeypatch.setattr(application.state.media_server, "authenticate_user", authenticate)
            emitted = AsyncMock()
            monkeypatch.setattr(application.state.sio, "emit", emitted)
            party_id = (await client.post("/api/party/create", json={})).json()["party_id"]
            identity = {"client_id": "host-client", "display_name": "Alice"}
            await client.post(f"/api/party/{party_id}/join", json=identity)
            party = application.state.party_manager.get(party_id)
            grant = party.host_session_grant
            cookie = client.cookies.get("ewp_session")
            sid = await _socket(application, "initial-engine", cookie)
            await application.state.sio.handlers["/"]["join_party"](
                sid, {"party_id": party_id, "username": "Alice", "client_id": "host-client"}
            )
            assert party.has_sid(sid)

            # Reproduce refresh ordering repeatedly, without a second F5:
            # old socket disconnects, new handshake freezes the cookie, then
            # HTTP session binding completes before join_party is emitted.
            for refresh in range(3):
                await application.state.sio.handlers["/"]["disconnect"](sid)
                left_at = party.host_left_at
                assert left_at is not None
                assert not application.state.party_manager.is_unlocked(party_id)
                sid = await _socket(application, f"refresh-engine-{refresh}", cookie)
                result = await client.post(f"/api/party/{party_id}/join", json=identity)

                assert result.json()["success"] is True
                assert result.json()["is_host"] is True
                assert result.json()["party_unlocked"] is False
                assert party.host_left_at == left_at
                assert party.host_session_grant == grant
                authenticate.assert_awaited_once()
                assert party_host_session_matches(party, "host-client", grant)

                await application.state.sio.handlers["/"]["join_party"](
                    sid, {"party_id": party_id, "username": "Alice", "client_id": "host-client"}
                )
                assert party.has_sid(sid)
                assert party.host_left_at is None
                assert application.state.party_manager.is_unlocked(party_id)
                assert party.host_session_grant == grant

            assert not [call for call in emitted.call_args_list if call.args[0] == "error"]

    asyncio.run(exercise())


def test_host_rebind_after_http_leave_preserves_its_valid_grant(tmp_path, monkeypatch):
    application = _application(tmp_path)

    async def exercise():
        async with asgi_client(application) as client:
            authenticate = AsyncMock(wraps=application.state.media_server.authenticate_user)
            monkeypatch.setattr(application.state.media_server, "authenticate_user", authenticate)
            emitted = AsyncMock()
            monkeypatch.setattr(application.state.sio, "emit", emitted)
            party_id = (await client.post("/api/party/create", json={})).json()["party_id"]
            identity = {"client_id": "host-client", "display_name": "Alice"}
            await client.post(f"/api/party/{party_id}/join", json=identity)
            party = application.state.party_manager.get(party_id)
            grant = party.host_session_grant
            old_sid = await _socket(
                application, "initial-engine", client.cookies.get("ewp_session")
            )
            await application.state.sio.handlers["/"]["join_party"](
                old_sid,
                {"party_id": party_id, "username": "Alice", "client_id": "host-client"},
            )

            assert (await client.post("/api/party/leave")).json()["success"] is True
            unbound = _session(client)
            assert "party_id" not in unbound
            assert "client_id" not in unbound
            assert unbound["host_session_grant"] == grant
            await application.state.sio.handlers["/"]["disconnect"](old_sid)
            left_at = party.host_left_at

            result = await client.post(f"/api/party/{party_id}/join", json=identity)
            assert result.json()["success"] is True
            assert result.json()["is_host"] is True
            assert result.json()["party_unlocked"] is False
            assert party.host_left_at == left_at
            assert _session(client)["host_session_grant"] == grant
            assert party.host_session_grant == grant
            authenticate.assert_awaited_once()

            # The replacement socket reads the rebound cookie, not the old
            # identity fields that HTTP leave deliberately removed.
            sid = await _socket(application, "rebound-engine", client.cookies.get("ewp_session"))
            await application.state.sio.handlers["/"]["join_party"](
                sid, {"party_id": party_id, "username": "Alice", "client_id": "host-client"}
            )
            assert party.has_sid(sid)
            assert party.host_left_at is None
            assert application.state.party_manager.is_unlocked(party_id)
            assert not [call for call in emitted.call_args_list if call.args[0] == "error"]

    asyncio.run(exercise())


def test_joining_a_different_party_as_guest_clears_a_foreign_host_grant(tmp_path):
    application = _application(tmp_path)

    async def exercise():
        async with asgi_client(application) as original:
            first_id = (await original.post("/api/party/create", json={})).json()["party_id"]
            await original.post(
                f"/api/party/{first_id}/join",
                json={"client_id": "first-host", "display_name": "Alice"},
            )
            original_grant = _session(original)["host_session_grant"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://testserver"
            ) as other:
                second_id = (await other.post("/api/party/create", json={})).json()["party_id"]
                await other.post(
                    f"/api/party/{second_id}/join",
                    json={"client_id": "second-host", "display_name": "Bob"},
                )
            second_party = application.state.party_manager.get(second_id)
            second_grant = second_party.host_session_grant
            assert second_grant != original_grant

            result = await original.post(
                f"/api/party/{second_id}/join",
                json={"client_id": "guest-client", "display_name": "Alice"},
            )
            assert result.json()["success"] is True
            assert result.json()["is_host"] is False
            assert "host_session_grant" not in _session(original)
            assert second_party.host_session_grant == second_grant
            assert (await original.get("/api/v2/auth/status")).json()["is_host"] is False
            assert (
                application.state.party_manager.get(first_id).host_session_grant == original_grant
            )

    asyncio.run(exercise())


@pytest.mark.parametrize("proof", ["missing", "invalid-signature", "wrong-grant"])
def test_host_refresh_does_not_accept_forged_or_unowned_identity(tmp_path, monkeypatch, proof):
    application = _application(tmp_path)

    async def exercise():
        async with asgi_client(application) as owner:
            authenticate = AsyncMock(wraps=application.state.media_server.authenticate_user)
            monkeypatch.setattr(application.state.media_server, "authenticate_user", authenticate)
            emitted = AsyncMock()
            monkeypatch.setattr(application.state.sio, "emit", emitted)
            party_id = (await owner.post("/api/party/create", json={})).json()["party_id"]
            await owner.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "host-client", "display_name": "Alice"},
            )
            party = application.state.party_manager.get(party_id)
            grant = party.host_session_grant
            application.state.party_manager.mark_host_left(party_id)
            if proof == "missing":
                cookie = None
            elif proof == "invalid-signature":
                cookie = "invalid-session-cookie"
            else:
                payload = base64.b64encode(
                    json.dumps(
                        {
                            "party_id": party_id,
                            "client_id": "host-client",
                            "host_session_grant": secrets.token_urlsafe(32),
                        }
                    ).encode()
                )
                cookie = TimestampSigner(TEST_SESSION_SECRET).sign(payload).decode()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://testserver"
            ) as attacker:
                result = await attacker.post(
                    f"/api/party/{party_id}/join",
                    json={"client_id": "host-client", "display_name": "Mallory"},
                    headers={"Cookie": f"ewp_session={cookie}"} if cookie else {},
                )
            assert result.json()["success"] is False
            assert result.json()["message"] == "Participant identity is already in use"
            authenticate.assert_awaited_once()
            assert party.host_session_grant == grant
            assert party.host_left_at is not None

            sid = await _socket(application, "attacker-engine", cookie)
            await application.state.sio.handlers["/"]["join_party"](
                sid, {"party_id": party_id, "username": "Mallory", "client_id": "host-client"}
            )
            assert not party.has_sid(sid)
            assert party.host_session_grant == grant
            assert party.host_left_at is not None
            assert any(call.args[0] == "error" for call in emitted.call_args_list)

    asyncio.run(exercise())
