"""Jellyfin adapter. Provider-specific operations grow here, not in callers."""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from backend.src.emby_client import EmbyClient, EmbyUnavailableError
from backend.src.emby_gateway import MediaServerGateway
from backend.src.providers.models import (
    AssetRequest,
    AuthenticatedUser,
    CatalogFilters,
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
from backend.src.quality import resolve_quality

# Same list the Emby path uses (stream_builder.build_params). Only consulted
# when a server omits IsTextSubtitleStream.
_IMAGE_SUBTITLE_CODECS = frozenset({"pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub"})

# Emby and Jellyfin both read -1 as "deliver no subtitle". null/absent means
# "no preference", which lets the server pick one from the account's
# SubtitlePlaybackMode. The two are not interchangeable.
NO_SUBTITLE = -1

# quality.py leaves 360p/240p/144p without a bitrate on purpose: Emby takes a
# resolution cap alone and picks a sensible rate itself. Jellyfin does not. Sent
# no MaxStreamingBitrate it encodes at `-b:v 0` and then downscales far past the
# cap; 360p was measured arriving as 416x234 at zero bitrate.
#
# So these are Jellyfin-side floors, not a change to the shared tier table, and
# Emby keeps choosing for itself. Each sits below the lowest 480p rung (420
# kbps) so the ladder stays monotonic -- the whole point of this exercise was a
# menu where a lower tier could cost more than a higher one -- while staying
# generous enough at these small frame sizes that Jellyfin does not look worse
# than Emby at the same selection.
_MIN_BITRATE_KBPS_BY_HEIGHT = {360: 400, 240: 250, 144: 150}


def _subtitle_must_be_burned_in(source: dict, subtitle_index: int) -> bool:
    """Whether Jellyfin has to draw this subtitle into the video itself.

    Only bitmap subtitles do. hls.js cannot render PGS or VobSub, so an image
    track reaches the viewer only if the server burns it in. Text tracks are
    fetched separately by the frontend as `<track>` elements via the subtitle
    asset route, exactly as on the Emby path (see stream_builder.build_params,
    which keeps the manifest path off for the same reason: two delivery paths
    fight over textTrack.mode).

    Jellyfin answers this directly with `IsTextSubtitleStream`, a non-nullable
    boolean in the API schema, so the codec list is only a fallback for a
    server that omits it.

    An unknown index, or a track we cannot classify, returns False. Not burning
    in is the recoverable failure: the viewer can still switch tracks, and the
    text path already covers the common case. Burning in the wrong track is
    baked into the video for the life of the stream.
    """
    for stream in source.get("MediaStreams") or []:
        if stream.get("Type") != "Subtitle" or stream.get("Index") != subtitle_index:
            continue
        is_text = stream.get("IsTextSubtitleStream")
        if is_text is not None:
            return not is_text
        return str(stream.get("Codec") or "").lower() in _IMAGE_SUBTITLE_CODECS
    return False


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
        filters = query.filters
        supported_query = replace(
            query,
            filters=CatalogFilters(
                playstate=filters.playstate,
                favorite=filters.favorite,
                genres=filters.genres,
                studios=filters.studios,
                person_ids=filters.person_ids,
                years=filters.years,
                official_ratings=filters.official_ratings,
                community_rating_min=filters.community_rating_min,
                critic_rating_min=filters.critic_rating_min,
            ),
        )
        payload = await self._client.query_items(
            emby_family_query(supported_query),
            access_token=credentials.access_token,
            user_id=credentials.user_id,
            root_items=True,
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

        catalogs = await asyncio.gather(
            catalog("/Genres"),
            catalog("/Studios"),
            return_exceptions=True,
        )
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
            {
                "id": "year",
                "label": "Year",
                "kind": "multi",
                "values": [
                    {"value": str(year), "label": str(year)}
                    for year in range(datetime.now(UTC).year, 1887, -1)
                ],
            },
            {
                "id": "official_rating",
                "label": "Parental rating",
                "kind": "multi",
                "values": [
                    {"value": rating, "label": rating}
                    for rating in (
                        "G",
                        "PG",
                        "PG-13",
                        "R",
                        "NC-17",
                        "TV-Y",
                        "TV-Y7",
                        "TV-G",
                        "TV-PG",
                        "TV-14",
                        "TV-MA",
                        "NR",
                        "Unrated",
                    )
                ],
            },
            {
                "id": "community_rating",
                "label": "Community rating",
                "kind": "select",
                "values": [
                    {"value": str(rating), "label": f"{rating}+"} for rating in range(5, 10)
                ],
            },
            {
                "id": "critic_rating",
                "label": "Critic rating",
                "kind": "select",
                "values": [
                    {"value": str(rating), "label": f"{rating}%+"} for rating in range(50, 100, 10)
                ],
            },
        ]
        for (control_id, label), payload in zip(
            (("genre", "Genre"), ("studio", "Studio")), catalogs, strict=True
        ):
            if not isinstance(payload, dict):
                continue
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
        # resolve_quality is the same source the Emby path uses
        # (stream_builder.build_params), so a tier means the same thing on both
        # providers. Scraping the id with a regex instead lost two things:
        #
        #   - the resolution. Jellyfin infers one from the bitrate when no cap
        #     is sent, so "480p" delivered 960x540: a label that lies, and more
        #     pixels sharing the same bits than the viewer asked for.
        #   - the three bitrate-free tiers. 360p/240p/144p carry no "-kbps"
        #     suffix by design (resolve_quality returns a resolution cap and no
        #     bitrate for them), so the regex missed and they fell to the
        #     10 Mbps default. Measured: 144p produced a byte-identical ffmpeg
        #     command to Auto, 14x the bitrate of 480p-1000, at full resolution.
        #     The bottom of the menu cost more than the middle.
        #
        # Auto returns (None, None, None) and must stay uncapped: that is the
        # only way a stream copy stays eligible, which is the whole point of
        # the tier (see quality.py's module docstring).
        max_width, max_height, bitrate_kbps = resolve_quality(request.quality)
        if bitrate_kbps is None and max_height is not None:
            bitrate_kbps = _MIN_BITRATE_KBPS_BY_HEIGHT.get(max_height)
        max_bitrate = bitrate_kbps * 1000 if bitrate_kbps else None
        video_codecs = [
            codec for codec in ("h264", "hevc", "av1", "vp9") if codec in request.client_codecs
        ]
        if not video_codecs:
            video_codecs = ["h264"]

        # Jellyfin takes resolution limits as ProfileConditions, not as the
        # MaxWidth/MaxHeight query parameters the Emby path appends.
        codec_profiles: list[dict] = []
        dimensions = [("Width", max_width), ("Height", max_height)]
        conditions = [
            {
                "Condition": "LessThanEqual",
                "Property": prop,
                "Value": str(value),
                "IsRequired": False,
            }
            for prop, value in dimensions
            if value is not None
        ]
        if conditions:
            codec_profiles.append({"Type": "Video", "Conditions": conditions})

        # Deliberately NOT request.subtitle_index. Naming a subtitle here asks
        # Jellyfin to deliver it, and its SubtitleProfiles below advertise only
        # vtt and srt as External, so anything else -- ass/ssa above all -- has
        # no matching profile and falls back to Encode, burning it into the
        # video. The frontend has meanwhile already loaded the same track as a
        # <track> element, so the viewer sees the line twice, offset. Text
        # tracks are the frontend's job; only bitmap tracks come back here, in
        # the second pass below.
        #
        # NO_SUBTITLE must be -1, not None. A null SubtitleStreamIndex means
        # "not specified", not "none": Jellyfin then falls back to the media
        # source's DefaultSubtitleStreamIndex, which follows the *user account's*
        # SubtitlePlaybackMode. An account set to Always play subtitles gets a
        # track auto-selected and, missing the vtt/srt profiles, burned in --
        # the exact bug this function exists to avoid, arriving via a route we
        # never asked for. httpx serialises None as JSON null rather than
        # omitting the key, so the Emby habit of filtering None out of params
        # (emby_client._params) does not carry over here.
        def build_body(subtitle_index: int) -> dict:
            return {
                "UserId": request.credentials.user_id,
                "MaxStreamingBitrate": max_bitrate,
                "StartTimeTicks": round(request.start_seconds * 10_000_000),
                "AudioStreamIndex": request.audio_index,
                "SubtitleStreamIndex": subtitle_index,
                # Explicit rather than relying on a SubtitleProfiles miss to
                # fall through to Encode: say what we mean in both directions.
                "AlwaysBurnInSubtitleWhenTranscoding": subtitle_index != NO_SUBTITLE,
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
                            # NOT ac3. A DeviceProfile states what the client
                            # can decode, and hls.js/MSE decodes AC-3 only on
                            # Safari. Listing it invites Jellyfin to stream-copy
                            # an AC-3 track straight through to a browser that
                            # renders silence, with no in-app way to recover.
                            # Same pair the Emby path sends (stream_builder).
                            "AudioCodec": "aac,mp3",
                            "Protocol": "hls",
                            "Context": "Streaming",
                            # Downmix rather than passing 5.1/7.1 through.
                            # Without it a surround track reaches a stereo
                            # browser at source channel count.
                            #
                            # No BreakOnNonKeyFrames here, unlike the Emby path.
                            # Jellyfin's DynamicHlsController refuses it and
                            # logs "Current HLS implementation doesn't support
                            # non-keyframe breaks but one is requested" on every
                            # transcode. Sending it buys nothing and fills the
                            # operator's log.
                            "MaxAudioChannels": "2",
                            # Jellyfin's own default, restated because turning
                            # it on is the second way to get doubled subtitles.
                            # It makes Jellyfin advertise subtitle renditions
                            # as #EXT-X-MEDIA in the manifest; the proxy
                            # rewrites every URI= faithfully, so hls.js builds
                            # a text track from it while the frontend has
                            # already added its own <track> for the same lines.
                            # The Emby path keeps the manifest route off for
                            # exactly this reason (stream_builder.build_params).
                            "EnableSubtitlesInManifest": False,
                            "MinSegments": 1,
                            "SegmentLength": 6,
                        }
                    ],
                    "ContainerProfiles": [],
                    "CodecProfiles": codec_profiles,
                    "SubtitleProfiles": [
                        {"Format": "vtt", "Method": "External"},
                        {"Format": "srt", "Method": "External"},
                    ],
                },
            }

        async def negotiate(subtitle_index: int) -> tuple[dict, dict | None]:
            response = await self._client.gateway.post(
                f"/Items/{request.item_id}/PlaybackInfo",
                headers=self._client._headers(
                    request.credentials.access_token, request.credentials.user_id
                ),
                json=build_body(subtitle_index),
            )
            response.raise_for_status()
            payload = response.json()
            sources = payload.get("MediaSources") or []
            return payload, next(
                (
                    row
                    for row in sources
                    if request.media_source_id is None or row.get("Id") == request.media_source_id
                ),
                None,
            )

        payload, source = await negotiate(NO_SUBTITLE)
        # The catalog only reaches us in the response, so the bitmap case costs
        # a second round trip. It is the rare one; text tracks, which is nearly
        # everything, still negotiate in a single call.
        if (
            request.subtitle_index is not None
            and source is not None
            and _subtitle_must_be_burned_in(source, request.subtitle_index)
        ):
            payload, source = await negotiate(request.subtitle_index)
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
        """Report a playback event. Returns success; never raises.

        The Protocol declares `-> bool` and the Emby side cannot raise:
        EmbyClient._report and stop_active_encodings both swallow
        httpx.HTTPError and return False. This has to match, because
        _stop_user_stream has no try/except around it and was written when
        the call physically could not fail. Letting an exception through
        there skips hls_registry.revoke for the viewer, aborts
        _stop_all_user_streams part-way so every remaining viewer keeps a
        live plan, and leaves the party with a video that will not stop.

        A stop report is also the only thing that tells Jellyfin to end the
        transcode, so a swallowed failure still costs an orphaned ffmpeg
        job. Losing one is better than wedging the party, but it is worth
        the warning.
        """
        try:
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
        except httpx.HTTPError as exc:
            self._client.logger.warning(
                "Jellyfin playback event failed: path=%s error=%s",
                path,
                type(exc).__name__,
            )
            return False

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
