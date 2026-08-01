"""Regression guard: the Emby admin token must never reach the browser.

Starlette's SessionMiddleware signs the session cookie but does not
encrypt it -- the payload is base64(json) with a signature appended, so
anything written into request.session is readable by anyone holding the
cookie, without the secret. An Emby admin access token grants control of
the whole Emby server, so it belongs server-side with only an opaque
handle in the cookie.

These tests decode the Set-Cookie exactly the way an attacker would.
"""

import base64
import json
import logging
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from backend.src.admin_session_store import AdminSessionStore
from backend.src.dependencies import (
    get_admin_session_store,
    get_emby_client,
    get_logger,
)
from backend.src.routers import admin

_SESSION_SECRET = "test-session-secret"
_SESSION_COOKIE = "ewp_session"
_ADMIN_TOKEN = "3f9a1c77d2e84b6ca0517e8b4d2f9c31"


class _EmbyClient:
    server_url = "http://emby.test"
    api_key = "admin-api-key"
    device_id = "emby-watchparty-test"


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {
            "AccessToken": _ADMIN_TOKEN,
            "User": {
                "Id": "8e21b0f4c9d34a7e",
                "Name": "Oratorian",
                "Policy": {"IsAdministrator": True},
            },
        }


def _decode_cookie(raw):
    """Recover the session payload the way a cookie holder can: no secret."""
    return json.loads(base64.b64decode(raw.split(".")[0]))


def _set_cookie_value(response):
    """Pull the ewp_session value straight out of the Set-Cookie header.

    Read from the header rather than the jar so the assertion covers the
    exact bytes sent to the browser, and so a pre-seeded cookie in the
    jar cannot shadow the response.
    """
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{_SESSION_COOKIE}="):
            return header.split("=", 1)[1].split(";", 1)[0]
    raise AssertionError("no ewp_session cookie in response")


class AdminSessionTests(unittest.TestCase):
    def setUp(self):
        self.store = AdminSessionStore(logger=logging.getLogger("test"))
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
                get_emby_client: lambda: _EmbyClient(),
                get_logger: lambda: logging.getLogger("test"),
                get_admin_session_store: lambda: self.store,
            }
        )
        self.client = TestClient(app)
        # The endpoint is rate limited per IP; tests share a process, so
        # clear the window rather than depending on test ordering.
        admin._LOGIN_ATTEMPTS.clear()

    def _login(self):
        with patch("backend.src.routers.admin.http_requests.post",
                   return_value=_Response()):
            return self.client.post(
                "/api/admin/login",
                json={"username": "Oratorian", "password": "hunter2"},
            )

    def test_admin_token_is_not_readable_from_the_session_cookie(self):
        response = self._login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        raw = _set_cookie_value(response)
        payload = _decode_cookie(raw)

        # The decisive assertion: the token must not appear anywhere in
        # the cookie, under any key.
        self.assertNotIn(_ADMIN_TOKEN, json.dumps(payload))
        self.assertNotIn(_ADMIN_TOKEN, raw)
        self.assertNotIn("admin_emby_token", payload)

    def test_cookie_carries_only_an_opaque_handle(self):
        payload = _decode_cookie(_set_cookie_value(self._login()))

        self.assertTrue(payload["admin_authenticated"])
        handle = payload["admin_session"]
        # The handle resolves to the credentials, but only server-side.
        stashed = self.store.get(handle)
        self.assertEqual(stashed["access_token"], _ADMIN_TOKEN)
        self.assertEqual(stashed["user_id"], "8e21b0f4c9d34a7e")

    def test_logout_destroys_the_stored_credentials(self):
        handle = _decode_cookie(_set_cookie_value(self._login()))["admin_session"]
        self.assertIsNotNone(self.store.get(handle))

        response = self.client.post("/api/admin/logout")

        self.assertEqual(response.status_code, 200)
        # Forgetting the handle is not enough; the token itself must go.
        self.assertIsNone(self.store.get(handle))

    def test_relogin_scrubs_a_legacy_plaintext_token_from_the_cookie(self):
        """An admin upgrading still carries the old readable token."""
        legacy = {
            "admin_authenticated": True,
            "admin_username": "Oratorian",
            "admin_emby_token": _ADMIN_TOKEN,
            "admin_emby_user_id": "8e21b0f4c9d34a7e",
            "admin_emby_is_admin": True,
        }
        import itsdangerous
        signed = itsdangerous.TimestampSigner(_SESSION_SECRET).sign(
            base64.b64encode(json.dumps(legacy).encode())
        ).decode()
        self.client.cookies.set(_SESSION_COOKIE, signed)

        response = self._login()

        payload = _decode_cookie(_set_cookie_value(response))
        self.assertNotIn("admin_emby_token", payload)
        self.assertNotIn(_ADMIN_TOKEN, json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
