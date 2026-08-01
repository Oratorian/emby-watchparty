import base64
import json
import unittest
from unittest.mock import patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from backend.src.dependencies import (
    get_admin_session_store,
    get_config,
    get_emby_client,
    get_logger,
    get_party_manager,
)
from backend.src.routers import admin
from backend.src.admin_session_store import AdminSessionStore
from backend.src.rate_limit import SlidingWindowRateLimiter


class _Config:
    TRUSTED_PROXY_CIDRS = ()

    def get_runtime_dict(self):
        return {"LOG_LEVEL": "INFO"}


class _EmbyClient:
    server_url = "http://emby.test"
    device_id = "test-device"


class _PartyManager:
    def get(self, _party_id):
        return None


class _Logger:
    def info(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, _message):
        pass


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-session-secret")
    app.include_router(admin.router)
    app.state.config = _Config()
    app.state.emby_client = _EmbyClient()
    app.state.party_manager = _PartyManager()
    app.state.logger = _Logger()
    app.state.admin_session_store = AdminSessionStore()
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.dependency_overrides.update(
        {
            get_config: lambda: app.state.config,
            get_emby_client: lambda: app.state.emby_client,
            get_party_manager: lambda: app.state.party_manager,
            get_logger: lambda: app.state.logger,
            get_admin_session_store: lambda: app.state.admin_session_store,
        }
    )
    return TestClient(app)


class AdminSessionSecurityTests(unittest.TestCase):
    def test_admin_login_keeps_emby_token_out_of_browser_cookie(self):
        upstream = requests.Response()
        upstream.status_code = 200
        upstream._content = json.dumps(
            {
                "AccessToken": "secret-upstream-token",
                "User": {
                    "Id": "admin-user",
                    "Name": "Alice",
                    "Policy": {"IsAdministrator": True},
                },
            }
        ).encode("utf-8")

        client = _client()
        with patch("backend.src.routers.admin.http_requests.post", return_value=upstream):
            response = client.post(
                "/api/admin/login",
                json={"username": "Alice", "password": "password"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "message": None})

        cookie = client.cookies.get("session")
        self.assertIsNotNone(cookie)
        unsigned_payload = cookie.split(".", 1)[0]
        decoded = base64.b64decode(unsigned_payload).decode("utf-8")
        self.assertNotIn("secret-upstream-token", decoded)

        config_response = client.get("/api/admin/config")
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(config_response.json()["LOG_LEVEL"], "INFO")


if __name__ == "__main__":
    unittest.main()
