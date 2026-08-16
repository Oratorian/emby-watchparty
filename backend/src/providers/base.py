"""Small interface implemented by concrete media-server adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from backend.src.providers.models import (
        AssetRequest,
        AuthenticatedUser,
        CatalogQuery,
        HLSResource,
        IntroSegment,
        MediaItemDetails,
        MediaPage,
        PlaybackEvent,
        PlaybackPlan,
        PlaybackRequest,
        ProviderCredentials,
        ProviderIdentity,
        ProviderReadiness,
        ProviderResponse,
        StreamCatalog,
    )


class MediaServerProvider(Protocol):
    identity: ProviderIdentity
    server_url: str
    api_key: str
    device_id: str

    async def readiness(self) -> ProviderReadiness: ...

    async def authenticate_user(self, username: str, password: str) -> AuthenticatedUser | None: ...

    async def verify_user(self, credentials: ProviderCredentials) -> bool: ...

    async def browse_libraries(self, credentials: ProviderCredentials | None) -> MediaPage: ...

    async def query_catalog(
        self, query: CatalogQuery, credentials: ProviderCredentials
    ) -> MediaPage: ...

    async def query_prefixes(
        self, query: CatalogQuery, credentials: ProviderCredentials
    ) -> tuple[str, ...]: ...

    async def get_filter_controls(
        self,
        parent_id: str | None,
        include_kinds: tuple[str, ...],
        media_kinds: tuple[str, ...],
        credentials: ProviderCredentials,
    ) -> tuple[dict, ...]: ...

    async def search_catalog(
        self, term: str, limit: int, credentials: ProviderCredentials
    ) -> MediaPage: ...

    async def get_details(
        self, item_id: str, credentials: ProviderCredentials
    ) -> MediaItemDetails | None: ...

    async def get_seasons(self, series_id: str, credentials: ProviderCredentials) -> MediaPage: ...

    async def get_episodes(
        self,
        series_id: str,
        season_id: str | None,
        credentials: ProviderCredentials,
    ) -> MediaPage: ...

    async def set_favorite(
        self, item_id: str, favorite: bool, credentials: ProviderCredentials
    ) -> None: ...

    async def set_played(
        self, item_id: str, played: bool, credentials: ProviderCredentials
    ) -> None: ...

    async def list_playlists(self, credentials: ProviderCredentials) -> MediaPage: ...

    async def create_playlist(self, name: str, credentials: ProviderCredentials) -> str: ...

    async def add_playlist_item(
        self, playlist_id: str, item_id: str, credentials: ProviderCredentials
    ) -> None: ...

    async def fetch_asset(self, request: AssetRequest) -> ProviderResponse: ...

    async def get_intro(
        self, item_id: str, credentials: ProviderCredentials
    ) -> IntroSegment | None: ...

    async def get_streams(
        self,
        item_id: str,
        media_source_id: str | None,
        credentials: ProviderCredentials,
    ) -> StreamCatalog: ...

    async def prepare_playback(self, request: PlaybackRequest) -> PlaybackPlan: ...

    async def report_playback(self, event: PlaybackEvent) -> bool: ...

    async def stop_playback(self, event: PlaybackEvent) -> bool: ...

    def resolve_hls_resource(
        self, plan: PlaybackPlan, parent: HLSResource, uri: str
    ) -> HLSResource: ...

    async def fetch_hls_resource(
        self,
        plan: PlaybackPlan,
        resource: HLSResource,
        *,
        range_header: str | None = None,
        head: bool = False,
    ) -> ProviderResponse: ...

    async def open_hls_resource(
        self,
        plan: PlaybackPlan,
        resource: HLSResource,
        *,
        range_header: str | None = None,
    ) -> ProviderResponse: ...
