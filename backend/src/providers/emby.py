"""Emby adapter preserving existing client behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from backend.src.providers.models import (
    AuthenticatedUser,
    CatalogQuery,
    ProviderCredentials,
    ProviderIdentity,
    ProviderReadiness,
)
from backend.src.providers.normalization import emby_family_query, normalize_page

if TYPE_CHECKING:
    from backend.src.emby_client import EmbyClient


class EmbyProvider:
    identity = ProviderIdentity(type="emby", display_name="Emby")

    def __init__(self, client: EmbyClient):
        self._client = client

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    @property
    def client(self) -> EmbyClient:
        return self._client

    async def readiness(self) -> ProviderReadiness:
        try:
            public = await self._client.gateway.get("/emby/System/Info/Public", timeout=2.0)
            authenticated = await self._client.gateway.get(
                "/emby/System/Info", headers=self._client._headers(), timeout=2.0
            )
        except httpx.HTTPError:
            return ProviderReadiness(reachable=False, credentials_valid=False)
        return ProviderReadiness(
            reachable=public.status_code == 200,
            credentials_valid=authenticated.status_code == 200,
        )

    async def authenticate_user(self, username: str, password: str) -> AuthenticatedUser | None:
        auth = await self._client.authenticate(username, password)
        if not auth:
            return None
        return AuthenticatedUser(
            credentials=ProviderCredentials(auth["access_token"], auth["user_id"]),
            username=auth["username"],
            is_admin=auth["is_admin"],
        )

    async def verify_user(self, credentials: ProviderCredentials) -> bool:
        return await self._client.verify_access_token(credentials.access_token, credentials.user_id)

    async def browse_libraries(self, credentials: ProviderCredentials | None):
        payload = await self._client.get_libraries(
            access_token=credentials.access_token if credentials else None,
            user_id=credentials.user_id if credentials else None,
        )
        return normalize_page(payload)

    async def query_catalog(self, query: CatalogQuery, credentials: ProviderCredentials):
        payload = await self._client.query_items(
            emby_family_query(query),
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )
        return normalize_page(payload)
