"""Media-server provider seam and concrete adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.src.emby_client import EmbyClient
from backend.src.providers.base import MediaServerProvider
from backend.src.providers.emby import EmbyProvider
from backend.src.providers.jellyfin import JellyfinProvider

if TYPE_CHECKING:
    from backend.src.config import Config
    from backend.src.emby_gateway import MediaServerGateway


def create_provider(
    config: Config, logger, gateway: MediaServerGateway
) -> EmbyProvider | JellyfinProvider:
    client = EmbyClient(config.MEDIA_SERVER_URL, config.MEDIA_SERVER_API_KEY, logger, gateway)
    if config.MEDIA_SERVER_TYPE == "jellyfin":
        return JellyfinProvider(client)
    return EmbyProvider(client)


__all__ = [
    "EmbyProvider",
    "JellyfinProvider",
    "MediaServerProvider",
    "create_provider",
]
