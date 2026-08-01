from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig


def _test_config() -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET="test-session-secret-with-at-least-32-characters",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def test_existing_user_can_create_and_join_party_through_public_http(
    tmp_path: Path,
) -> None:
    application = create_app(
        config=_test_config(),
        project_root=tmp_path,
        enable_update_check=False,
    )

    with TestClient(application) as client:
        created = client.post("/api/party/create", json={})
        assert created.status_code == 200
        party_id = created.json()["party_id"]
        assert party_id

        joined = client.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "client-1", "display_name": "Alice"},
        )
        assert joined.status_code == 200
        assert joined.json()["success"] is True
        assert joined.json()["party_id"] == party_id
        assert client.cookies.get("ewp_session")
