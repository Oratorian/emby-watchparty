import logging

import httpx

from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers import EmbyProvider, JellyfinProvider, create_provider


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
