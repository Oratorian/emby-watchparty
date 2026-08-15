"""Small interface implemented by concrete media-server adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from backend.src.providers.models import (
        AuthenticatedUser,
        MediaPage,
        PlaybackEvent,
        PlaybackPlan,
        PlaybackRequest,
        ProviderCredentials,
        ProviderIdentity,
        ProviderReadiness,
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

    async def prepare_playback(self, request: PlaybackRequest) -> PlaybackPlan: ...

    async def report_playback(self, event: PlaybackEvent) -> bool: ...

    async def stop_playback(self, event: PlaybackEvent) -> bool: ...
