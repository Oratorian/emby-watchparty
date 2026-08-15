"""Jellyfin adapter. Provider-specific operations grow here, not in callers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.src.providers.models import ProviderIdentity

if TYPE_CHECKING:
    from backend.src.emby_client import EmbyClient


class JellyfinProvider:
    identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

    def __init__(self, client: EmbyClient):
        self._client = client

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    @property
    def client(self) -> EmbyClient:
        return self._client
