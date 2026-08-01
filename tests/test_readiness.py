import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.dependencies import get_avatar_store, get_config, get_emby_gateway
from backend.src.routers import health


class _Config:
    EMBY_SERVER_URL = "http://emby.test"
    EMBY_API_KEY = "admin-key"


class _Response:
    status_code = 200


class _EmbyGateway:
    async def get(self, *_args, **_kwargs):
        return _Response()


class _AvatarStore:
    def readiness_check(self):
        return True


def _client(config=None):
    app = FastAPI()
    app.include_router(health.router)
    app.dependency_overrides[get_config] = lambda: config or _Config()
    app.dependency_overrides[get_emby_gateway] = lambda: _EmbyGateway()
    app.dependency_overrides[get_avatar_store] = lambda: _AvatarStore()
    return TestClient(app)


class ReadinessTests(unittest.TestCase):
    def test_ready_when_required_config_and_emby_are_available(self):
        response = _client().get("/api/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(
            response.json()["checks"],
            {"config": True, "storage": True, "emby": True},
        )

    def test_not_ready_when_emby_api_key_is_missing(self):
        config = _Config()
        config.EMBY_API_KEY = ""
        response = _client(config).get("/api/ready")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["checks"]["config"])


if __name__ == "__main__":
    unittest.main()
