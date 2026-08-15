"""Emby adapter preserving existing client behavior."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import httpx

from backend.src.providers.models import (
    AuthenticatedUser,
    CatalogQuery,
    HLSResource,
    PlaybackEvent,
    PlaybackEventType,
    PlaybackMethod,
    PlaybackPlan,
    PlaybackPlanError,
    PlaybackRequest,
    ProviderCredentials,
    ProviderIdentity,
    ProviderReadiness,
)
from backend.src.providers.normalization import (
    emby_family_query,
    normalize_details,
    normalize_page,
)

if TYPE_CHECKING:
    from backend.src.config import Config
    from backend.src.emby_client import EmbyClient


class EmbyProvider:
    identity = ProviderIdentity(type="emby", display_name="Emby")

    def __init__(self, client: EmbyClient, config: Config):
        self._client = client
        self._config = config

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

    async def search_catalog(self, term: str, limit: int, credentials: ProviderCredentials):
        from backend.src.providers.models import CatalogPage, CatalogScope

        return await self.query_catalog(
            CatalogQuery(
                scope=CatalogScope(
                    include_kinds=("movie", "series", "episode", "person", "box_set"),
                    recursive=True,
                ),
                page=CatalogPage(limit=limit),
                search_term=term,
            ),
            credentials,
        )

    async def get_details(self, item_id: str, credentials: ProviderCredentials):
        payload = await self._client.get_item_details(
            item_id,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )
        return normalize_details(payload) if payload else None

    async def prepare_playback(self, request: PlaybackRequest) -> PlaybackPlan:
        from backend.src.quality import resolve_quality
        from backend.src.stream_builder import StreamBuilder

        _, _, bitrate_kbps = resolve_quality(request.quality)
        playback_info = await self._client.get_playback_info(
            request.item_id,
            audio_index=request.audio_index,
            subtitle_index=request.subtitle_index,
            media_source_id=request.media_source_id,
            max_streaming_bitrate=bitrate_kbps * 1000 if bitrate_kbps else None,
            start_time_ticks=round(request.start_seconds * 10_000_000),
            access_token=request.credentials.access_token,
            user_id=request.credentials.user_id,
        )
        sources = playback_info.get("MediaSources") if playback_info else None
        if not sources:
            raise PlaybackPlanError("Emby returned no playable HLS media source")
        source = sources[0]
        media_source_id = source.get("Id")
        play_session_id = playback_info.get("PlaySessionId")
        if not media_source_id or not play_session_id:
            raise PlaybackPlanError("Emby returned an incomplete HLS playback plan")
        browser_path = StreamBuilder(
            self._client, self._client.logger, self._config
        ).build_stream_url(
            item_id=request.item_id,
            app_prefix=self._config.APP_PREFIX,
            media_source=source,
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            audio_index=request.audio_index,
            subtitle_index=request.subtitle_index,
            quality=request.quality,
            start_time_ticks=(
                round(request.start_seconds * 10_000_000) if request.start_seconds > 0 else None
            ),
            client_codecs=set(request.client_codecs),
        )
        query = browser_path.split("?", 1)[1] if "?" in browser_path else ""
        upstream = f"{self._client.server_url}/emby/Videos/{request.item_id}/master.m3u8"
        if query:
            upstream = f"{upstream}?{query}"
        stream_id = secrets.token_urlsafe(18)
        return PlaybackPlan(
            stream_id=stream_id,
            item_id=request.item_id,
            media_source_id=str(media_source_id),
            play_session_id=str(play_session_id),
            method=(
                PlaybackMethod.HLS_TRANSCODE
                if "TranscodeReasons=" in browser_path
                else PlaybackMethod.HLS_COPY
            ),
            master=HLSResource(upstream),
            credentials=request.credentials,
            browser_path=browser_path,
        )

    async def report_playback(self, event: PlaybackEvent) -> bool:
        common = {
            "item_id": event.item_id,
            "media_source_id": event.media_source_id,
            "play_session_id": event.play_session_id,
            "position_seconds": event.position_seconds,
            "audio_index": event.audio_index,
            "subtitle_index": event.subtitle_index,
            "run_time_seconds": event.run_time_seconds,
            "access_token": event.credentials.access_token,
            "user_id": event.credentials.user_id,
        }
        if event.type is PlaybackEventType.START:
            return await self._client.report_playback_start(**common)
        if event.type is PlaybackEventType.PROGRESS:
            return await self._client.report_playback_progress(
                **common,
                is_paused=event.is_paused,
            )
        raise ValueError("stop events must use stop_playback")

    async def stop_playback(self, event: PlaybackEvent) -> bool:
        reported = await self._client.report_playback_stopped(
            item_id=event.item_id,
            media_source_id=event.media_source_id,
            play_session_id=event.play_session_id,
            position_seconds=event.position_seconds,
            run_time_seconds=event.run_time_seconds,
            access_token=event.credentials.access_token,
            user_id=event.credentials.user_id,
        )
        cleaned = await self._client.stop_active_encodings(
            play_session_id=event.play_session_id,
            access_token=event.credentials.access_token,
        )
        return bool(reported and cleaned)
