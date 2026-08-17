from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from scripts.generate_openapi_types import main, openapi_document


def test_generated_openapi_types_have_no_drift(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["generate_openapi_types.py", "--check"])
    assert main() == 0


def test_generated_openapi_uses_the_production_route_surface(tmp_path) -> None:
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="emby",
            MEDIA_SERVER_URL="http://emby.test",
            MEDIA_SERVER_API_KEY="test-key",
            APP_ENV="development",
            SESSION_SECRET="s" * 32,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )
    application = create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
    )

    assert set(openapi_document()["paths"]) == set(application.openapi()["paths"])
