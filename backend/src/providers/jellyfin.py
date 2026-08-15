"""Jellyfin adapter. Provider-specific operations grow here, not in callers."""

from __future__ import annotations

import re
import secrets
from urllib.parse import unquote, urljoin, urlparse

import httpx

from backend.src.emby_client import EmbyClient
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers.models import (
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
    UnsafeProviderResourceError,
)
from backend.src.providers.normalization import (
    emby_family_query,
    normalize_details,
    normalize_page,
)


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

    async def readiness(self) -> ProviderReadiness:
        try:
            public = await self._client.gateway.get("/System/Info/Public", timeout=2.0)
            authenticated = await self._client.gateway.get(
                "/System/Info", headers=self._client._headers(), timeout=2.0
            )
        except httpx.HTTPError:
            return ProviderReadiness(reachable=False, credentials_valid=False)
        return ProviderReadiness(
            reachable=public.status_code == 200,
            credentials_valid=authenticated.status_code == 200,
        )

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
        bitrate_match = re.search(r"-(\d+)$", request.quality)
        max_bitrate = int(bitrate_match.group(1)) * 1000 if bitrate_match else 10_000_000
        video_codecs = [
            codec for codec in ("h264", "hevc", "av1", "vp9") if codec in request.client_codecs
        ]
        if not video_codecs:
            video_codecs = ["h264"]
        body = {
            "UserId": request.credentials.user_id,
            "MaxStreamingBitrate": max_bitrate,
            "StartTimeTicks": round(request.start_seconds * 10_000_000),
            "AudioStreamIndex": request.audio_index,
            "SubtitleStreamIndex": request.subtitle_index,
            "MediaSourceId": request.media_source_id,
            "EnableDirectPlay": False,
            "EnableDirectStream": True,
            "EnableTranscoding": True,
            "AllowVideoStreamCopy": not request.force_transcode,
            "AllowAudioStreamCopy": True,
            "DeviceProfile": {
                "Name": "Emby Watch Party HLS",
                "MaxStreamingBitrate": max_bitrate,
                "DirectPlayProfiles": [],
                "TranscodingProfiles": [
                    {
                        "Container": "ts",
                        "Type": "Video",
                        "VideoCodec": ",".join(video_codecs),
                        "AudioCodec": "aac,mp3,ac3",
                        "Protocol": "hls",
                        "Context": "Streaming",
                        "EnableSubtitlesInManifest": True,
                        "MinSegments": 1,
                        "SegmentLength": 6,
                    }
                ],
                "ContainerProfiles": [],
                "CodecProfiles": [],
                "SubtitleProfiles": [
                    {"Format": "vtt", "Method": "External"},
                    {"Format": "srt", "Method": "External"},
                ],
            },
        }
        response = await self._client.gateway.post(
            f"/Items/{request.item_id}/PlaybackInfo",
            headers=self._client._headers(
                request.credentials.access_token, request.credentials.user_id
            ),
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        sources = payload.get("MediaSources") or []
        source = next(
            (
                row
                for row in sources
                if request.media_source_id is None or row.get("Id") == request.media_source_id
            ),
            None,
        )
        play_session_id = payload.get("PlaySessionId")
        if not source or not source.get("Id") or not play_session_id:
            raise PlaybackPlanError("Jellyfin returned no playable HLS media source")
        transcoding_url = source.get("TranscodingUrl")
        if not transcoding_url or source.get("TranscodingSubProtocol") != "hls":
            raise PlaybackPlanError("Jellyfin returned a non-HLS playback plan")
        master_url = urljoin(f"{self._client.server_url}/", transcoding_url)
        configured = urlparse(self._client.server_url)
        resolved = urlparse(master_url)
        if (
            resolved.scheme not in {"http", "https"}
            or (resolved.scheme, resolved.netloc) != (configured.scheme, configured.netloc)
            or not resolved.path.lower().endswith(".m3u8")
            or f"/videos/{request.item_id.lower()}/" not in resolved.path.lower()
        ):
            raise PlaybackPlanError("Jellyfin returned an unsafe HLS playback plan")
        reasons = source.get("TranscodingReasons") or []
        method = PlaybackMethod.HLS_TRANSCODE if reasons else PlaybackMethod.HLS_REMUX
        stream_id = secrets.token_urlsafe(18)
        return PlaybackPlan(
            stream_id=stream_id,
            item_id=request.item_id,
            media_source_id=str(source["Id"]),
            play_session_id=str(play_session_id),
            method=method,
            master=HLSResource(master_url),
            credentials=request.credentials,
            browser_path=f"/hls/{stream_id}/master.m3u8",
            upstream_headers={
                key: str(value) for key, value in (source.get("RequiredHttpHeaders") or {}).items()
            },
        )

    async def report_playback(self, event: PlaybackEvent) -> bool:
        path = {
            PlaybackEventType.START: "/Sessions/Playing",
            PlaybackEventType.PROGRESS: "/Sessions/Playing/Progress",
        }.get(event.type)
        if path is None:
            raise ValueError("stop events must use stop_playback")
        return await self._send_playback_event(path, event)

    async def stop_playback(self, event: PlaybackEvent) -> bool:
        return await self._send_playback_event("/Sessions/Playing/Stopped", event)

    async def _send_playback_event(self, path: str, event: PlaybackEvent) -> bool:
        response = await self._client.gateway.post(
            path,
            headers=self._client._headers(
                event.credentials.access_token,
                event.credentials.user_id,
            ),
            json={
                "ItemId": event.item_id,
                "MediaSourceId": event.media_source_id,
                "PlaySessionId": event.play_session_id,
                "PositionTicks": round(event.position_seconds * 10_000_000),
                "IsPaused": event.is_paused,
                "CanSeek": True,
            },
        )
        response.raise_for_status()
        return True

    def resolve_hls_resource(
        self, plan: PlaybackPlan, parent: HLSResource, uri: str
    ) -> HLSResource:
        decoded = uri
        for _ in range(8):
            expanded = unquote(decoded)
            if expanded == decoded:
                break
            decoded = expanded
        else:
            raise UnsafeProviderResourceError("HLS URI exceeded decoding limit")
        if not decoded or any(
            ord(character) < 32 or ord(character) == 127 for character in decoded
        ):
            raise UnsafeProviderResourceError("HLS URI contains unsafe characters")
        path = urlparse(decoded.replace("\\", "/")).path
        if any(part in {".", ".."} for part in path.split("/")):
            raise UnsafeProviderResourceError("HLS URI contains traversal")

        child_url = urljoin(parent.url, uri)
        configured = urlparse(self._client.server_url)
        child = urlparse(child_url)
        root = urlparse(plan.master.url).path.rsplit("/", 1)[0] + "/"
        if (
            child.scheme not in {"http", "https"}
            or (child.scheme, child.netloc) != (configured.scheme, configured.netloc)
            or child.fragment
            or not child.path.startswith(root)
        ):
            raise UnsafeProviderResourceError("HLS URI is outside the playback plan")
        return HLSResource(child_url)

    async def fetch_hls_resource(
        self,
        plan: PlaybackPlan,
        resource: HLSResource,
        *,
        range_header: str | None = None,
    ) -> httpx.Response:
        if resource != plan.master and resource not in plan.resources.values():
            raise UnsafeProviderResourceError("HLS resource is not registered")
        headers = self._client._headers(
            plan.credentials.access_token,
            plan.credentials.user_id,
        )
        headers.update(plan.upstream_headers)
        if range_header:
            headers["Range"] = range_header
        return await self._client.gateway.get(
            resource.url,
            headers=headers,
            timeout=30.0,
        )


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
