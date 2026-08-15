"""Jellyfin adapter. Provider-specific operations grow here, not in callers."""

from __future__ import annotations

from backend.src.emby_client import EmbyClient
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers.models import ProviderCredentials, ProviderIdentity
from backend.src.providers.normalization import normalize_page


class JellyfinProvider:
    identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")

    def __init__(self, client: EmbyClient):
        self._client = EmbyClient(
            client.server_url,
            client.api_key,
            client.logger,
            _JellyfinGateway(client.gateway),
        )

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    @property
    def client(self) -> EmbyClient:
        return self._client

    async def get_libraries(self, access_token=None, user_id=None):
        response = await self._client.gateway.get(
            "/UserViews",
            headers=self._client._headers(access_token, user_id),
            params={"userId": user_id} if user_id else None,
        )
        response.raise_for_status()
        return response.json()

    async def browse_libraries(self, credentials: ProviderCredentials | None):
        payload = await self.get_libraries(
            access_token=credentials.access_token if credentials else None,
            user_id=credentials.user_id if credentials else None,
        )
        return normalize_page(payload)


class _JellyfinGateway(MediaServerGateway):
    """Translate inherited Emby-family paths to Jellyfin root paths."""

    def __init__(self, gateway):
        self._gateway = gateway

    @staticmethod
    def _path(path: str) -> str:
        return path[5:] if path.startswith("/emby/") else path

    async def get(self, path: str, **kwargs):
        return await self._gateway.get(self._path(path), **kwargs)

    async def post(self, path: str, **kwargs):
        return await self._gateway.post(self._path(path), **kwargs)

    async def delete(self, path: str, **kwargs):
        return await self._gateway.delete(self._path(path), **kwargs)

    async def open_stream(self, path: str, **kwargs):
        return await self._gateway.open_stream(self._path(path), **kwargs)
