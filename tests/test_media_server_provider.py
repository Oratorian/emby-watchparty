import asyncio
import logging

import httpx

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers import EmbyProvider, JellyfinProvider, create_provider
from tests.support.asgi import asgi_client
from tests.support.fake_jellyfin import FakeJellyfinState, create_fake_jellyfin_app


def _config(provider: str) -> Config:
    return Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            EMBY_SERVER_URL="http://emby.test",
            EMBY_API_KEY="emby-key",
            APP_ENV="development",
            SESSION_SECRET="",
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            MEDIA_SERVER_TYPE=provider,
            JELLYFIN_SERVER_URL="http://jellyfin.test",
            JELLYFIN_API_KEY="jellyfin-key",
        ),
        RuntimeConfig(LOG_TO_FILE=False),
    )


def test_factory_selects_emby_adapter_without_changing_client_surface() -> None:
    config = _config("emby")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))

    provider = create_provider(config, logging.getLogger("test"), gateway)

    assert isinstance(provider, EmbyProvider)
    assert provider.identity.type == "emby"
    assert provider.server_url == "http://emby.test"
    assert provider.get_libraries is not None


def test_factory_selects_jellyfin_adapter() -> None:
    config = _config("jellyfin")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    gateway = MediaServerGateway(client, config.MEDIA_SERVER_URL, logging.getLogger("test"))

    provider = create_provider(config, logging.getLogger("test"), gateway)

    assert isinstance(provider, JellyfinProvider)
    assert provider.identity.type == "jellyfin"
    assert provider.server_url == "http://jellyfin.test"


def test_app_lifespan_installs_selected_provider(tmp_path) -> None:
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
    )

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.media_server.identity.type == "jellyfin"
            assert app.state.emby_client is app.state.media_server
            assert app.state.socket_context["media_server"] is app.state.media_server

    asyncio.run(exercise())


def test_jellyfin_user_can_authenticate_and_browse_v2_library(tmp_path) -> None:
    fake_state = FakeJellyfinState()
    fake = create_fake_jellyfin_app(fake_state)
    app = create_app(
        config=_config("jellyfin"),
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=fake),
    )

    async def exercise() -> None:
        async with asgi_client(app) as client:
            created = await client.post(
                "/api/party/create",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            party_id = created.json()["party_id"]
            joined = await client.post(
                f"/api/party/{party_id}/join",
                json={"client_id": "client-1", "display_name": "Alice"},
            )
            assert joined.status_code == 200

            login = await client.post(
                "/api/v2/auth/login",
                json={"username": "Alice", "password": "secret"},
            )
            assert login.status_code == 200
            assert login.json()["media_server_type"] == "jellyfin"
            assert login.json()["success"] is True

            libraries = await client.get("/api/v2/libraries")
            assert libraries.status_code == 200
            assert libraries.json() == {
                "items": [
                    {
                        "id": "jellyfin-library-1",
                        "name": "Movies",
                        "kind": "collection_folder",
                        "collection_kind": "movies",
                        "overview": "",
                        "runtime_seconds": None,
                        "production_year": None,
                        "parent_id": None,
                        "series_id": None,
                        "series_name": None,
                        "season_id": None,
                        "season_name": None,
                        "index_number": None,
                        "parent_index_number": None,
                        "is_folder": True,
                        "is_playable": False,
                        "is_browsable": True,
                        "has_primary_image": True,
                        "backdrop_count": 0,
                        "primary_image_aspect_ratio": None,
                        "user_state": {
                            "playback_position_seconds": 0.0,
                            "played_percentage": None,
                            "played": False,
                            "favorite": False,
                        },
                        "media_source_count": 0,
                    }
                ],
                "total": 1,
                "start": 0,
            }

    asyncio.run(exercise())
    assert all(not request["path"].startswith("/emby/") for request in fake_state.requests)
