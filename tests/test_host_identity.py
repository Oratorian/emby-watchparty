"""Regression guard: a scraped client_id must not confer host or admin rights.

`host_client_id` is broadcast to every party member in the `host_changed`
event, and `POST /api/party/<id>/join` stores whatever `client_id` the
caller sends. So matching on client_id alone let any attendee re-join
supplying the host's id, receive a validly signed cookie carrying that
identity, and reach `/api/admin/config` whenever the host's Emby account
was an administrator.

Proof of host identity is now `host_session_grant`, minted server-side by
`set_host` and written only to the real host's cookie.
"""

import base64
import json
import logging
import unittest

import itsdangerous
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from backend.src.dependencies import (
    _owns_host_identity,
    get_config,
    get_logger,
    get_party_manager,
)
from backend.src.party_manager import PartyManager
from backend.src.routers import admin

_SESSION_SECRET = "test-session-secret"
_SESSION_COOKIE = "ewp_session"

_HOST_CLIENT_ID = "host-client-id"
_ATTACKER_CLIENT_ID = "attacker-client-id"


class _Config:
    STATIC_SESSION_ENABLED = False
    STATIC_SESSION_ID = ""

    def get_runtime_dict(self):
        return {"REQUIRE_LOGIN": False}


class _PartyManager:
    """Stands in for PartyManager, holding one hosted party."""

    def __init__(self, party):
        self._party = party

    def get(self, party_id):
        return self._party if party_id == "PARTY" else None


def _cookie(**payload):
    data = base64.b64encode(json.dumps(payload).encode("utf-8"))
    return itsdangerous.TimestampSigner(_SESSION_SECRET).sign(data).decode("utf-8")


class HostIdentityTests(unittest.TestCase):
    def setUp(self):
        # A real PartyManager so set_host's actual grant minting is under
        # test rather than a hand-written stand-in.
        self.pm = PartyManager(config=_Config(), logger=logging.getLogger("test"))
        self.pm.watch_parties["PARTY"] = self.pm._new_party_dict("PARTY")
        self.grant = self.pm.set_host(
            "PARTY",
            client_id=_HOST_CLIENT_ID,
            user_id="emby-user",
            access_token="host-token",
            username="Oratorian",
            is_admin=True,
        )
        self.party = self.pm.watch_parties["PARTY"]

        app = FastAPI()
        app.include_router(admin.router)
        app.add_middleware(
            SessionMiddleware,
            secret_key=_SESSION_SECRET,
            session_cookie=_SESSION_COOKIE,
            same_site="lax",
            https_only=False,
        )
        app.dependency_overrides.update(
            {
                get_config: lambda: _Config(),
                get_logger: lambda: logging.getLogger("test"),
                get_party_manager: lambda: _PartyManager(self.party),
            }
        )
        self.app = app

    def _client(self, **session):
        c = TestClient(self.app)
        c.cookies.set(_SESSION_COOKIE, _cookie(**session))
        return c

    # -- the attack -------------------------------------------------------

    def test_scraped_host_client_id_does_not_grant_admin(self):
        """The exploit: host_client_id is public, so it cannot be the key."""
        attacker = self._client(
            party_id="PARTY",
            client_id=_HOST_CLIENT_ID,  # scraped from host_changed
            display_name="Mallory",
        )

        response = attacker.get("/api/admin/config")

        self.assertEqual(response.json().get("error"), "Not authenticated")

    def test_real_host_still_reaches_admin(self):
        host = self._client(
            party_id="PARTY",
            client_id=_HOST_CLIENT_ID,
            display_name="Oratorian",
            host_session_grant=self.grant,
        )

        response = host.get("/api/admin/config")

        body = response.json()
        self.assertIsNone(body.get("error"), body)
        self.assertIn("REQUIRE_LOGIN", body)

    def test_forged_grant_is_rejected(self):
        attacker = self._client(
            party_id="PARTY",
            client_id=_HOST_CLIENT_ID,
            display_name="Mallory",
            host_session_grant="not-the-real-grant",
        )

        response = attacker.get("/api/admin/config")

        self.assertEqual(response.json().get("error"), "Not authenticated")

    # -- grant lifecycle --------------------------------------------------

    def test_grant_is_rotated_when_the_host_changes(self):
        """A previous host's cookie must stop proving anything."""
        old_grant = self.grant
        new_grant = self.pm.set_host(
            "PARTY",
            client_id="second-host",
            user_id="emby-user-2",
            access_token="host-token-2",
            username="Someone Else",
            is_admin=True,
        )

        self.assertNotEqual(old_grant, new_grant)
        self.assertFalse(
            _owns_host_identity(self.party, _HOST_CLIENT_ID, old_grant)
        )
        self.assertTrue(
            _owns_host_identity(self.party, "second-host", new_grant)
        )

    def test_clear_host_invalidates_the_grant(self):
        self.pm.clear_host("PARTY")

        self.assertIsNone(self.party["host_session_grant"])
        self.assertFalse(
            _owns_host_identity(self.party, _HOST_CLIENT_ID, self.grant)
        )

    def test_grant_alone_is_not_enough_without_the_matching_client_id(self):
        self.assertFalse(
            _owns_host_identity(self.party, _ATTACKER_CLIENT_ID, self.grant)
        )

    def test_hostless_party_cannot_be_satisfied_by_any_grant(self):
        self.pm.clear_host("PARTY")

        self.assertFalse(_owns_host_identity(self.party, None, None))
        self.assertFalse(_owns_host_identity(self.party, _HOST_CLIENT_ID, ""))


if __name__ == "__main__":
    unittest.main()
