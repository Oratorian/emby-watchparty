"""Jellyfin adapter. Provider-specific operations grow here, not in callers."""

from __future__ import annotations

import asyncio
import re
import secrets
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from backend.src.emby_client import EmbyClient, EmbyUnavailableError
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers.models import (
    AssetRequest,
    AuthenticatedUser,
    CatalogQuery,
    HLSResource,
    IntroSegment,
    MediaServerUnavailableError,
    PlaybackEvent,
    PlaybackEventType,
    PlaybackMethod,
    PlaybackPlan,
    PlaybackPlanError,
    PlaybackRequest,
    ProviderCapabilities,
    ProviderCredentials,
    ProviderIdentity,
    ProviderReadiness,
    UnsafeProviderResourceError,
)
from backend.src.providers.normalization import (
    emby_family_query,
    normalize_details,
    normalize_page,
    normalize_stream_catalog,
)


class JellyfinProvider:
    identity = ProviderIdentity(type="jellyfin", display_name="Jellyfin")
    capabilities = ProviderCapabilities(filter_controls=True)

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

    async def authenticate_user(self, username: str, password: str) -> AuthenticatedUser | None:
        try:
            auth = await self._client.authenticate(username, password)
        except EmbyUnavailableError as exc:
            raise MediaServerUnavailableError from exc
        if not auth:
            return None
        return AuthenticatedUser(
            credentials=ProviderCredentials(auth["access_token"], auth["user_id"]),
            username=auth["username"],
            is_admin=auth["is_admin"],
        )

    async def verify_user(self, credentials: ProviderCredentials) -> bool:
        return await self._client.verify_access_token(credentials.access_token, credentials.user_id)

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

    async def query_prefixes(self, query: CatalogQuery, credentials: ProviderCredentials):
        provider_query = emby_family_query(query)
        probes = await asyncio.gather(
            *(
                self._client.query_items(
                    provider_query,
                    access_token=credentials.access_token,
                    user_id=credentials.user_id,
                    name_starts_with=prefix,
                )
                for prefix in ("", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            )
        )
        total = int(probes[0].get("TotalRecordCount") or 0)
        available = [
            prefix
            for prefix, result in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", probes[1:], strict=True)
            if int(result.get("TotalRecordCount") or 0) > 0
        ]
        letter_total = sum(int(result.get("TotalRecordCount") or 0) for result in probes[1:])
        if total > letter_total:
            available.append("#")
        return tuple(available)

    async def get_filter_controls(
        self,
        parent_id: str | None,
        include_kinds: tuple[str, ...],
        media_kinds: tuple[str, ...],
        credentials: ProviderCredentials,
    ) -> tuple[dict, ...]:
        # Jellyfin's dedicated genre/studio controllers support user, parent,
        # and item-type scoping. They do not accept media type or recursion.
        del media_kinds
        params = {
            key: value
            for key, value in {
                "userId": credentials.user_id,
                "parentId": parent_id,
                "includeItemTypes": ",".join(
                    "".join(part.title() for part in kind.split("_")) for kind in include_kinds
                ),
                "enableImages": "false",
            }.items()
            if value
        }

        async def catalog(path: str) -> dict:
            response = await self._client.gateway.get(
                path,
                headers=self._client._headers(
                    credentials.access_token,
                    credentials.user_id,
                ),
                params=params,
            )
            response.raise_for_status()
            return response.json()

        genres, studios = await asyncio.gather(catalog("/Genres"), catalog("/Studios"))
        controls: list[dict] = [
            {
                "id": "playstate",
                "label": "Playstate",
                "kind": "select",
                "values": [
                    {"value": "any", "label": "Any"},
                    {"value": "unplayed", "label": "Unplayed"},
                    {"value": "played", "label": "Played"},
                    {"value": "resumable", "label": "In progress"},
                ],
            },
            {"id": "favorite", "label": "Favorite", "kind": "toggle", "values": []},
        ]
        for control_id, label, payload in (
            ("genre", "Genre", genres),
            ("studio", "Studio", studios),
        ):
            values = [
                {"value": str(item["Name"]), "label": str(item["Name"])}
                for item in payload.get("Items", [])
                if isinstance(item, dict) and item.get("Name")
            ]
            if values:
                controls.append(
                    {"id": control_id, "label": label, "kind": "multi", "values": values}
                )
        return tuple(controls)

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

    async def get_section(self, item_id: str, section: str, credentials: ProviderCredentials):
        items = await self._client.get_item_section(
            item_id,
            section,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )
        return normalize_page({"Items": items, "TotalRecordCount": len(items)})

    async def get_seasons(self, series_id: str, credentials: ProviderCredentials):
        items = await self._client.get_series_seasons(
            series_id,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )
        return normalize_page({"Items": items, "TotalRecordCount": len(items)})

    async def get_episodes(
        self,
        series_id: str,
        season_id: str | None,
        credentials: ProviderCredentials,
    ):
        items = await self._client.get_series_episodes(
            series_id,
            season_id,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )
        return normalize_page({"Items": items, "TotalRecordCount": len(items)})

    async def set_favorite(
        self, item_id: str, favorite: bool, credentials: ProviderCredentials
    ) -> None:
        await self._client.set_favorite(
            item_id,
            favorite,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )

    async def set_played(
        self, item_id: str, played: bool, credentials: ProviderCredentials
    ) -> None:
        await self._client.set_played(
            item_id,
            played,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )

    async def list_playlists(self, credentials: ProviderCredentials):
        items = await self._client.get_playlists(
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )
        return normalize_page({"Items": items, "TotalRecordCount": len(items)})

    async def create_playlist(self, name: str, credentials: ProviderCredentials) -> str:
        return await self._client.create_playlist(
            name,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )

    async def add_playlist_item(
        self, playlist_id: str, item_id: str, credentials: ProviderCredentials
    ) -> None:
        await self._client.add_to_playlist(
            playlist_id,
            item_id,
            access_token=credentials.access_token,
            user_id=credentials.user_id,
        )

    async def fetch_asset(self, request: AssetRequest) -> httpx.Response:
        if request.kind == "avatar":
            return await self._client.gateway.get(
                f"/Users/{quote(request.item_id, safe='')}/Images/Primary",
                headers=self._client._headers(
                    request.credentials.access_token,
                    request.credentials.user_id,
                ),
                timeout=10,
            )
        if request.kind == "subtitle":
            if request.media_source_id is None or request.index is None:
                raise ValueError("subtitle asset requires source and index")
            path = (
                f"/Videos/{quote(request.item_id, safe='')}/"
                f"{quote(request.media_source_id, safe='')}/Subtitles/{request.index}/Stream.vtt"
            )
            return await self._client.gateway.get(
                path,
                headers=self._client._headers(
                    request.credentials.access_token,
                    request.credentials.user_id,
                ),
            )
        image_type = "".join(part.title() for part in request.kind.split("_"))
        path = f"/Items/{quote(request.item_id, safe='')}/Images/{image_type}"
        if request.index is not None:
            path += f"/{request.index}"
        params = {
            key: value
            for key, value in {
                "maxWidth": request.max_width,
                "maxHeight": request.max_height,
                "quality": request.quality,
            }.items()
            if value is not None
        }
        return await self._client.gateway.get(
            path,
            headers=self._client._headers(
                request.credentials.access_token,
                request.credentials.user_id,
            ),
            params=params,
        )

    async def get_intro(
        self, item_id: str, credentials: ProviderCredentials
    ) -> IntroSegment | None:
        response = await self._client.gateway.get(
            f"/MediaSegments/{quote(item_id, safe='')}",
            headers=self._client._headers(credentials.access_token, credentials.user_id),
        )
        response.raise_for_status()
        row = next(
            (
                item
                for item in response.json().get("Items", [])
                if str(item.get("Type", "")).lower() == "intro"
            ),
            None,
        )
        if row is None:
            return None
        return IntroSegment(
            start_seconds=float(row.get("StartTicks") or 0) / 10_000_000,
            end_seconds=float(row.get("EndTicks") or 0) / 10_000_000,
        )

    async def get_streams(
        self,
        item_id: str,
        media_source_id: str | None,
        credentials: ProviderCredentials,
    ):
        async def posted(source_id: str | None):
            body = {"UserId": credentials.user_id}
            if source_id:
                body["MediaSourceId"] = source_id
            response = await self._client.gateway.post(
                f"/Items/{quote(item_id, safe='')}/PlaybackInfo",
                headers=self._client._headers(credentials.access_token, credentials.user_id),
                json=body,
            )
            response.raise_for_status()
            return response.json()

        scoped = await posted(media_source_id)
        full = await posted(None) if media_source_id else scoped
        return normalize_stream_catalog(scoped, full)

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
        path_parts = resolved.path.strip("/").split("/")
        path_item_id = (
            path_parts[1] if len(path_parts) >= 3 and path_parts[0].lower() == "videos" else ""
        )

        def canonical_item_id(value: str) -> str:
            compact = value.replace("-", "").lower()
            return compact if re.fullmatch(r"[0-9a-f]{32}", compact) else value.lower()

        if (
            resolved.scheme not in {"http", "https"}
            or (resolved.scheme, resolved.netloc) != (configured.scheme, configured.netloc)
            or not resolved.path.lower().endswith(".m3u8")
            or canonical_item_id(path_item_id) != canonical_item_id(request.item_id)
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
        head: bool = False,
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
        fetch = self._client.gateway.head if head else self._client.gateway.get
        return await fetch(
            resource.url,
            headers=headers,
            timeout=30.0,
        )

    async def open_hls_resource(
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
        return await self._client.gateway.open_stream(resource.url, headers=headers)


class _JellyfinGateway(MediaServerGateway):
    """Translate inherited Emby-family paths to Jellyfin root paths."""

    def __init__(self, gateway):
        self._gateway = gateway

    @staticmethod
    def _path(path: str) -> str:
        return path[5:] if path.startswith("/emby/") else path

    async def get(self, path: str, **kwargs):
        return await self._gateway.get(self._path(path), **kwargs)

    async def head(self, path: str, **kwargs):
        return await self._gateway.head(self._path(path), **kwargs)

    async def post(self, path: str, **kwargs):
        return await self._gateway.post(self._path(path), **kwargs)

    async def delete(self, path: str, **kwargs):
        return await self._gateway.delete(self._path(path), **kwargs)

    async def open_stream(self, path: str, **kwargs):
        return await self._gateway.open_stream(self._path(path), **kwargs)
