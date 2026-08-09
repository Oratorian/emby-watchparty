"""Async, user-scoped Emby API operations."""

from __future__ import annotations

import asyncio
import secrets
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from backend.src.emby_gateway import EmbyGateway


class EmbyUnavailableError(Exception):
    """The configured Emby endpoint could not be reached."""


class EmbyClient:
    def __init__(self, server_url: str, api_key: str, logger, gateway: EmbyGateway):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.logger = logger
        self.gateway = gateway
        self.device_id = "emby-watchparty-" + secrets.token_hex(8)
        self._library_collection_types: dict[str, dict[str, str | None]] = {}

    def _headers(self, access_token=None, user_id=None) -> dict[str, str]:
        if access_token:
            auth_value = (
                f'Emby UserId="{user_id or ""}", Client="WatchParty", '
                f'Device="Web", DeviceId="{self.device_id}", Version="1.0", '
                f'Token="{access_token}"'
            )
            return {
                "X-Emby-Token": access_token,
                "Content-Type": "application/json",
                "X-Emby-Authorization": auth_value,
            }
        return {"X-Emby-Token": self.api_key, "Content-Type": "application/json"}

    def _auth_param(self, access_token=None) -> str:
        return access_token or self.api_key

    async def authenticate(self, username: str, password: str) -> dict | None:
        headers = {
            "Content-Type": "application/json",
            "X-Emby-Authorization": (
                f'Emby Client="WatchParty", Device="Web", '
                f'DeviceId="{self.device_id}", Version="1.0"'
            ),
        }
        try:
            response = await self.gateway.post(
                "/emby/Users/AuthenticateByName",
                headers=headers,
                json={"Username": username, "Pw": password},
            )
            response.raise_for_status()
            data = response.json()
            access_token = data.get("AccessToken")
            user = data.get("User") or {}
            user_id = user.get("Id")
            if not access_token or not user_id:
                self.logger.error("Emby auth response missing AccessToken or User.Id")
                return None
            await self._register_device_capabilities(access_token, user_id)
            return {
                "access_token": access_token,
                "user_id": user_id,
                "username": user.get("Name", username),
                "is_admin": bool((user.get("Policy") or {}).get("IsAdministrator")),
            }
        except httpx.RequestError as exc:
            self.logger.error(
                "Emby authentication failed: error=%s",
                type(exc).__name__,
            )
            raise EmbyUnavailableError from exc
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "Emby authentication failed: error=%s",
                type(exc).__name__,
            )
            return None

    _authenticate_user = authenticate

    async def _register_device_capabilities(self, access_token=None, user_id=None):
        capabilities = {
            "PlayableMediaTypes": ["Video", "Audio"],
            "SupportedCommands": [],
            "SupportsMediaControl": False,
            "SupportsPersistentIdentifier": False,
            "DeviceProfile": {
                "MaxStreamingBitrate": 10_000_000,
                "TranscodingProfiles": [
                    {
                        "Container": "ts",
                        "Type": "Video",
                        "VideoCodec": "h264",
                        "AudioCodec": "aac,mp3",
                        "Protocol": "hls",
                    }
                ],
                "DirectPlayProfiles": [
                    {
                        "Container": "mp4,mkv",
                        "Type": "Video",
                        "VideoCodec": "h264",
                        "AudioCodec": "aac,mp3",
                    }
                ],
                "SubtitleProfiles": [
                    {"Format": "vtt", "Method": "External"},
                    {"Format": "srt", "Method": "External"},
                    {"Format": "pgs", "Method": "Encode"},
                    {"Format": "pgssub", "Method": "Encode"},
                    {"Format": "dvdsub", "Method": "Encode"},
                ],
            },
        }
        try:
            response = await self.gateway.post(
                "/emby/Sessions/Capabilities/Full",
                headers=self._headers(access_token, user_id),
                json=capabilities,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.logger.warning(
                "Failed to register device capabilities: error=%s",
                type(exc).__name__,
            )

    async def verify_access_token(self, access_token: str, user_id: str) -> bool:
        if not access_token or not user_id:
            return False
        try:
            response = await self.gateway.get(
                f"/emby/Users/{user_id}",
                headers=self._headers(access_token, user_id),
                timeout=2.0,
            )
            return response.status_code == 200
        except httpx.HTTPError as exc:
            self.logger.warning("verify_access_token error=%s", type(exc).__name__)
            return False

    async def get_libraries(self, access_token=None, user_id=None):
        path = f"/emby/Users/{user_id}/Views" if user_id else "/emby/Library/MediaFolders"
        try:
            response = await self.gateway.get(path, headers=self._headers(access_token, user_id))
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            self.logger.error("Error fetching libraries: error=%s", type(exc).__name__)
            return {"Items": []}

    async def _ensure_library_cache(self, access_token=None, user_id=None) -> None:
        cache_key = user_id or "_anon_"
        if cache_key in self._library_collection_types:
            return
        libraries = await self.get_libraries(access_token, user_id)
        self._library_collection_types[cache_key] = {
            item["Id"]: item.get("CollectionType")
            for item in libraries.get("Items", [])
            if item.get("Id")
        }

    async def _resolve_item_scope(
        self, parent_id, item_type, recursive, access_token, user_id
    ) -> tuple[str | None, bool]:
        effective_type = item_type
        effective_recursive = recursive
        if parent_id and not item_type and not recursive:
            await self._ensure_library_cache(access_token, user_id)
            collection_type = self._library_collection_types.get(user_id or "_anon_", {}).get(
                parent_id
            )
            collection_types = {
                "movies": "Movie",
                "tvshows": "Series",
                "boxsets": "BoxSet",
                "music": "MusicArtist",
                "homevideos": "Movie,Video,Photo",
                "photos": "Movie,Video,Photo",
            }
            effective_type = collection_types.get(collection_type) if collection_type else None
            if effective_type:
                effective_recursive = True
        return effective_type, effective_recursive

    async def get_items(
        self,
        parent_id=None,
        item_type=None,
        recursive=False,
        start_index=None,
        limit=None,
        sort_mode="default",
        anchor_prefix=None,
        access_token=None,
        user_id=None,
    ):
        effective_type, effective_recursive = await self._resolve_item_scope(
            parent_id, item_type, recursive, access_token, user_id
        )
        path = f"/emby/Users/{user_id}/Items" if user_id else "/emby/Items"
        fields = (
            "Overview,PrimaryImageAspectRatio,ProductionYear,IndexNumber,"
            "ParentIndexNumber,SeriesId,SeasonId,UserData,MediaSourceCount"
        )
        if sort_mode == "alphabetical":
            fields += ",SortName"
        params: dict[str, str | int] = {
            "Recursive": str(effective_recursive).lower(),
            "Fields": fields,
            "SortBy": (
                "SortName"
                if sort_mode == "alphabetical"
                else "ParentIndexNumber,IndexNumber,SortName"
            ),
            "SortOrder": "Ascending",
        }
        if parent_id:
            params["ParentId"] = parent_id
        if effective_type:
            params["IncludeItemTypes"] = effective_type
        headers = self._headers(access_token, user_id)
        headers["Cache-Control"] = "no-cache"
        if sort_mode == "alphabetical" and anchor_prefix:
            count_params = {
                **params,
                "NameLessThan": anchor_prefix,
                "StartIndex": 0,
                "Limit": 1,
            }
            count_response = await self.gateway.get(path, headers=headers, params=count_params)
            count_response.raise_for_status()
            start_index = int(count_response.json().get("TotalRecordCount") or 0)
        resolved_start_index = int(start_index or 0)
        params["StartIndex"] = resolved_start_index
        if limit is not None:
            params["Limit"] = limit
        response = await self.gateway.get(path, headers=headers, params=params)
        response.raise_for_status()
        result = response.json()
        result["StartIndex"] = resolved_start_index
        return result

    async def get_item_prefixes(
        self,
        parent_id=None,
        item_type=None,
        recursive=False,
        access_token=None,
        user_id=None,
    ):
        effective_type, effective_recursive = await self._resolve_item_scope(
            parent_id, item_type, recursive, access_token, user_id
        )
        params: dict[str, str] = {
            "UserId": user_id or "",
            "Recursive": str(effective_recursive).lower(),
            "SortBy": "SortName",
            "SortOrder": "Ascending",
        }
        if parent_id:
            params["ParentId"] = parent_id
        if effective_type:
            params["IncludeItemTypes"] = effective_type
        response = await self.gateway.get(
            "/emby/Items/Prefixes",
            headers=self._headers(access_token, user_id),
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def query_items(self, query, access_token=None, user_id=None):
        """Run a strict watchparty library query through Emby's allowlisted API."""
        if not user_id:
            return {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}

        scope = query["scope"]
        page = query["page"]
        sort = query["sort"]
        filters = query["filters"]
        params: dict[str, str | int] = {
            "Recursive": str(scope["recursive"]).lower(),
            "Fields": (
                "Overview,PrimaryImageAspectRatio,ProductionYear,IndexNumber,"
                "ParentIndexNumber,SeriesId,SeasonId,UserData,MediaSourceCount"
            ),
            "SortBy": sort["field"],
            "SortOrder": sort["direction"],
            "StartIndex": page["start_index"],
            "Limit": page["limit"],
        }

        scalar_values = {
            "ParentId": scope["parent_id"],
            "IncludeItemTypes": ",".join(scope["include_item_types"]),
            "MediaTypes": ",".join(scope["media_types"]),
            "SearchTerm": query.get("search_term"),
        }
        params.update({key: value for key, value in scalar_values.items() if value})

        playstate = {
            "played": "IsPlayed",
            "unplayed": "IsUnplayed",
            "resumable": "IsResumable",
        }.get(filters["playstate"])
        if playstate:
            params["Filters"] = playstate

        boolean_values = {
            "IsFavorite": filters["favorite"],
            "IsDuplicate": filters["duplicates"],
            "Is3D": filters["is_3d"],
        }
        params.update(
            {
                key: str(value).lower()
                for key, value in boolean_values.items()
                if value is not None
            }
        )

        list_values = {
            "Genres": (filters["genres"], "|"),
            "OfficialRatings": (filters["official_ratings"], "|"),
            "Studios": (filters["studios"], "|"),
            "Tags": (filters["tags"], "|"),
            "Years": (filters["years"], ","),
            "Containers": (filters["containers"], ","),
            "VideoCodecs": (filters["video_codecs"], ","),
            "VideoTypes": (filters["video_types"], ","),
            "AudioCodecs": (filters["audio_codecs"], ","),
            "AudioLayouts": (filters["audio_layouts"], ","),
            "AudioLanguages": (filters["audio_languages"], ","),
            "SubtitleCodecs": (filters["subtitle_codecs"], ","),
            "SubtitleLanguages": (filters["subtitle_languages"], ","),
        }
        for key, (values, separator) in list_values.items():
            if values:
                params[key] = separator.join(str(value) for value in values)

        truth_values = {
            "HasSubtitles": filters["subtitles"],
            "HasTrailer": filters["trailers"],
            "HasSpecialFeature": filters["extras"],
            "HasThemeSong": filters["theme_songs"],
            "HasThemeVideo": filters["theme_videos"],
            "IsLocked": filters["locked"],
            "HasOverview": filters["overview"],
        }
        for key, value in truth_values.items():
            if value in {"with", "yes"}:
                params[key] = "true"
            elif value in {"without", "no"}:
                params[key] = "false"

        provider_params = {"imdb": "HasImdbId", "tmdb": "HasTmdbId", "tvdb": "HasTvdbId"}
        for provider in filters["missing_provider_ids"]:
            params[provider_params[provider]] = "false"

        response = await self.gateway.get(
            f"/emby/Users/{user_id}/Items",
            headers=self._headers(access_token, user_id),
            params=params,
        )
        response.raise_for_status()
        result = response.json()
        result["StartIndex"] = page["start_index"]
        return result

    async def get_filter_options(
        self,
        *,
        parent_id=None,
        include_item_types=None,
        media_types=None,
        access_token=None,
        user_id=None,
    ):
        params = {
            "UserId": user_id or "",
            "Recursive": "true",
            "ParentId": parent_id or "",
            "IncludeItemTypes": include_item_types or "",
            "MediaTypes": media_types or "",
            "Limit": 200,
        }
        paths = {
            "genre": "/emby/Genres",
            "studio": "/emby/Studios",
            "tag": "/emby/Tags",
            "year": "/emby/Years",
            "official_rating": "/emby/OfficialRatings",
            "container": "/emby/Containers",
            "video_codec": "/emby/VideoCodecs",
            "audio_codec": "/emby/AudioCodecs",
            "audio_layout": "/emby/AudioLayouts",
            "subtitle_codec": "/emby/SubtitleCodecs",
        }

        async def fetch(path):
            try:
                response = await self.gateway.get(
                    path,
                    headers=self._headers(access_token, user_id),
                    params={key: value for key, value in params.items() if value != ""},
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return None

        responses = await asyncio.gather(*(fetch(path) for path in paths.values()))
        return dict(zip(paths, responses, strict=True))

    async def get_season_episodes(self, season_id, access_token=None, user_id=None):
        path = f"/emby/Users/{user_id}/Items" if user_id else "/emby/Items"
        params = {
            "ParentId": season_id,
            "IncludeItemTypes": "Episode",
            "Recursive": "false",
            "Fields": (
                "Overview,PrimaryImageAspectRatio,IndexNumber,ParentIndexNumber,"
                "SeriesId,SeasonId,RunTimeTicks,UserData"
            ),
            "SortBy": "ParentIndexNumber,IndexNumber",
            "SortOrder": "Ascending",
        }
        try:
            response = await self.gateway.get(
                path,
                headers=self._headers(access_token, user_id),
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            self.logger.error("Error fetching season episodes: error=%s", type(exc).__name__)
            return {"Items": [], "TotalRecordCount": 0}

    async def get_item_details(self, item_id, access_token=None, user_id=None):
        if not user_id:
            return None
        headers = self._headers(access_token, user_id)
        params = {"api_key": self._auth_param(access_token)}
        response = await self.gateway.get(
            f"/emby/Users/{user_id}/Items/{item_id}", headers=headers, params=params
        )
        if response.status_code == 404:
            response = await self.gateway.get(
                f"/emby/Items/{item_id}", headers=headers, params=params
            )
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            self.logger.error("Error fetching item details: error=%s", type(exc).__name__)
            return None

    async def search_items(
        self,
        query,
        access_token=None,
        user_id=None,
        include_item_types="Movie,Series",
    ):
        if not user_id:
            return {"Items": []}

        params = {
            "SearchTerm": query,
            "Recursive": "true",
            "Fields": (
                "Overview,PrimaryImageAspectRatio,ProductionYear,UserData,"
                "RunTimeTicks,MediaSourceCount,IndexNumber,ParentIndexNumber,"
                "SeriesId,SeasonId"
            ),
            "IncludeItemTypes": include_item_types,
            "api_key": self._auth_param(access_token),
        }
        try:
            response = await self.gateway.get(
                f"/emby/Users/{user_id}/Items",
                headers=self._headers(access_token, user_id),
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            self.logger.error("Error searching items: error=%s", type(exc).__name__)
            return {"Items": []}

    async def get_item_section(
        self, item_id, section, access_token=None, user_id=None
    ):
        routes = {
            "related": (f"/emby/Items/{item_id}/Similar", {"UserId": user_id, "Limit": 12}),
            "trailers": (f"/emby/Users/{user_id}/Items/{item_id}/LocalTrailers", {}),
            "extras": (f"/emby/Users/{user_id}/Items/{item_id}/SpecialFeatures", {}),
        }
        path, params = routes[section]
        response = await self.gateway.get(
            path,
            headers=self._headers(access_token, user_id),
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("Items", []) if isinstance(payload, dict) else payload

    async def set_favorite(
        self, item_id, favorite, access_token=None, user_id=None
    ):
        path = f"/emby/Users/{user_id}/FavoriteItems/{item_id}"
        method = self.gateway.post if favorite else self.gateway.delete
        response = await method(path, headers=self._headers(access_token, user_id))
        response.raise_for_status()

    async def set_played(self, item_id, played, access_token=None, user_id=None):
        path = f"/emby/Users/{user_id}/PlayedItems/{item_id}"
        method = self.gateway.post if played else self.gateway.delete
        response = await method(path, headers=self._headers(access_token, user_id))
        response.raise_for_status()

    async def get_playlists(self, access_token=None, user_id=None):
        response = await self.gateway.get(
            f"/emby/Users/{user_id}/Items",
            headers=self._headers(access_token, user_id),
            params={"Recursive": "true", "IncludeItemTypes": "Playlist"},
        )
        response.raise_for_status()
        return response.json().get("Items", [])

    async def create_playlist(self, name, access_token=None, user_id=None):
        response = await self.gateway.post(
            "/emby/Playlists",
            headers=self._headers(access_token, user_id),
            params={"Name": name, "UserId": user_id},
        )
        response.raise_for_status()
        return response.json()["Id"]

    async def add_to_playlist(
        self, playlist_id, item_id, access_token=None, user_id=None
    ):
        response = await self.gateway.post(
            f"/emby/Playlists/{playlist_id}/Items",
            headers=self._headers(access_token, user_id),
            params={"Ids": item_id, "UserId": user_id},
        )
        response.raise_for_status()

    def get_image_url(
        self,
        item_id,
        image_type="Primary",
        access_token=None,
        max_width=None,
        max_height=None,
        quality=None,
    ):
        params = [f"api_key={self._auth_param(access_token)}"]
        if max_width:
            params.append(f"maxWidth={int(max_width)}")
        if max_height:
            params.append(f"maxHeight={int(max_height)}")
        if quality:
            params.append(f"quality={int(quality)}")
        return f"{self.server_url}/emby/Items/{item_id}/Images/{image_type}?{'&'.join(params)}"

    async def get_playback_info(
        self,
        item_id,
        audio_index=None,
        subtitle_index=None,
        media_source_id=None,
        max_streaming_bitrate=None,
        start_time_ticks=None,
        access_token=None,
        user_id=None,
    ):
        if not user_id:
            return None
        params: dict[str, str | int] = {
            "UserId": user_id,
            "api_key": self._auth_param(access_token),
            "IsPlayback": "true",
            "AutoOpenLiveStream": "true",
            "StartTimeTicks": start_time_ticks or 0,
        }
        optional = {
            "MaxStreamingBitrate": max_streaming_bitrate,
            "AudioStreamIndex": audio_index,
            "SubtitleStreamIndex": subtitle_index,
            "MediaSourceId": media_source_id,
        }
        params.update({key: value for key, value in optional.items() if value is not None})
        try:
            response = await self.gateway.post(
                f"/emby/Items/{item_id}/PlaybackInfo",
                headers=self._headers(access_token, user_id),
                params=params,
                json={},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            self.logger.error("Error fetching playback info: error=%s", type(exc).__name__)
            return await self.get_item_details(item_id, access_token, user_id)

    async def stop_active_encodings(self, play_session_id=None, access_token=None):
        params = {"DeviceId": self.device_id, "api_key": self._auth_param(access_token)}
        if play_session_id:
            params["PlaySessionId"] = play_session_id
        try:
            response = await self.gateway.delete(
                "/emby/Videos/ActiveEncodings",
                headers=self._headers(access_token),
                params=params,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            self.logger.warning("Failed to stop active encodings: error=%s", type(exc).__name__)
            return False

    @staticmethod
    def _seconds_to_ticks(seconds):
        return int(seconds * 10_000_000)

    def _build_playback_payload(
        self,
        item_id,
        media_source_id,
        play_session_id,
        position_seconds,
        is_paused,
        audio_index=None,
        subtitle_index=None,
        run_time_seconds=None,
    ):
        payload = {
            "ItemId": item_id,
            "MediaSourceId": media_source_id,
            "PlaySessionId": play_session_id,
            "PositionTicks": self._seconds_to_ticks(position_seconds),
            "IsPaused": is_paused,
            "CanSeek": True,
            "PlayMethod": "Transcode",
            "QueueableMediaTypes": ["Video"],
        }
        if audio_index is not None:
            payload["AudioStreamIndex"] = audio_index
        if subtitle_index is not None:
            payload["SubtitleStreamIndex"] = subtitle_index
        if run_time_seconds is not None:
            payload["RunTimeTicks"] = self._seconds_to_ticks(run_time_seconds)
        return payload

    async def _report(self, path, payload, access_token, user_id) -> bool:
        try:
            response = await self.gateway.post(
                path,
                headers=self._headers(access_token, user_id),
                json=payload,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            self.logger.warning("Playback report failed: error=%s", type(exc).__name__)
            return False

    async def report_playback_start(
        self,
        item_id,
        media_source_id,
        play_session_id,
        position_seconds=0,
        audio_index=None,
        subtitle_index=None,
        run_time_seconds=None,
        access_token=None,
        user_id=None,
    ):
        payload = self._build_playback_payload(
            item_id,
            media_source_id,
            play_session_id,
            position_seconds,
            False,
            audio_index,
            subtitle_index,
            run_time_seconds,
        )
        return await self._report("/emby/Sessions/Playing", payload, access_token, user_id)

    async def report_playback_progress(
        self,
        item_id,
        media_source_id,
        play_session_id,
        position_seconds,
        is_paused,
        event_name="TimeUpdate",
        audio_index=None,
        subtitle_index=None,
        run_time_seconds=None,
        access_token=None,
        user_id=None,
    ):
        payload = self._build_playback_payload(
            item_id,
            media_source_id,
            play_session_id,
            position_seconds,
            is_paused,
            audio_index,
            subtitle_index,
            run_time_seconds,
        )
        payload["EventName"] = event_name
        return await self._report("/emby/Sessions/Playing/Progress", payload, access_token, user_id)

    async def report_playback_stopped(
        self,
        item_id,
        media_source_id,
        play_session_id,
        position_seconds,
        run_time_seconds=None,
        access_token=None,
        user_id=None,
    ):
        payload = {
            "ItemId": item_id,
            "MediaSourceId": media_source_id,
            "PlaySessionId": play_session_id,
            "PositionTicks": self._seconds_to_ticks(position_seconds),
        }
        if run_time_seconds is not None:
            payload["RunTimeTicks"] = self._seconds_to_ticks(run_time_seconds)
        return await self._report("/emby/Sessions/Playing/Stopped", payload, access_token, user_id)
