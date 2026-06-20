"""
Emby Client Module
Handles all interactions with the Emby Server API.

This module is stateless with respect to user identity. The admin api_key
is used only for non-user-scoped requests (raw image bytes, server
diagnostics). Every user-scoped call accepts an `access_token` and
`user_id` so the host of each party can drive its own Emby session.
"""

import requests
import secrets


class EmbyClient:
    """Client for interacting with Emby Server API"""

    def __init__(self, server_url, api_key, logger):
        """
        Initialize Emby client.

        Args:
            server_url: Base URL of the Emby server
            api_key: Admin API key (used for non-user-scoped endpoints only)
            logger: Logger instance
        """
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.logger = logger
        self.device_id = "emby-watchparty-" + secrets.token_hex(8)
        # Per-user CollectionType cache so library navigation can pick the
        # right IncludeItemTypes / Recursive flags. Each host has its own
        # ACL so we cache per user_id.
        self._library_collection_types: dict = {}

    # =========================================================================
    # Request helpers
    # =========================================================================

    def _headers(self, access_token=None, user_id=None) -> dict:
        """Build request headers, scoped to a host token when supplied."""
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
        # Admin api_key fallback. Use this only for non-user-scoped calls.
        return {"X-Emby-Token": self.api_key, "Content-Type": "application/json"}

    def _auth_param(self, access_token=None) -> str:
        """Return the right api_key value for query strings."""
        return access_token or self.api_key

    # =========================================================================
    # Authentication
    # =========================================================================

    def authenticate(self, username: str, password: str) -> dict | None:
        """Authenticate a user against Emby. Returns auth data or None.

        Does NOT mutate the client. Callers (the auth router) store the
        returned access_token in party state via PartyManager.set_host().

        Returns:
            {
                "access_token": str,
                "user_id": str,
                "username": str,
                "is_admin": bool,
            }
            or None on failure.
        """
        try:
            url = f"{self.server_url}/emby/Users/AuthenticateByName"
            headers = {
                "Content-Type": "application/json",
                "X-Emby-Authorization": (
                    f'Emby Client="WatchParty", Device="Web", '
                    f'DeviceId="{self.device_id}", Version="1.0"'
                ),
            }
            payload = {"Username": username, "Pw": password}

            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            access_token = data.get("AccessToken")
            user = data.get("User") or {}
            user_id = user.get("Id")
            policy = user.get("Policy") or {}
            is_admin = bool(policy.get("IsAdministrator"))

            if not access_token or not user_id:
                self.logger.error(
                    "Emby auth response missing AccessToken or User.Id"
                )
                return None

            self._register_device_capabilities(access_token, user_id)

            self.logger.info(
                f"Authenticated Emby user {user.get('Name', '?')} "
                f"(id={user_id}, admin={is_admin})"
            )
            return {
                "access_token": access_token,
                "user_id": user_id,
                "username": user.get("Name", username),
                "is_admin": is_admin,
            }
        except Exception as e:
            self.logger.error(f"Emby authentication failed: {e}")
            return None

    # Backward compatibility alias. New callers should use authenticate().
    _authenticate_user = authenticate

    def _register_device_capabilities(self, access_token=None, user_id=None):
        """Register device capabilities so Emby produces correct transcodes."""
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
                        "Protocol": "hls"
                    }
                ],
                "DirectPlayProfiles": [
                    {
                        "Container": "mp4,mkv",
                        "Type": "Video",
                        "VideoCodec": "h264",
                        "AudioCodec": "aac,mp3"
                    }
                ],
                "SubtitleProfiles": [
                    {"Format": "vtt", "Method": "External"},
                    {"Format": "srt", "Method": "External"},
                    {"Format": "pgs", "Method": "Encode"},
                    {"Format": "pgssub", "Method": "Encode"},
                    {"Format": "dvdsub", "Method": "Encode"}
                ]
            }
        }
        try:
            url = f"{self.server_url}/emby/Sessions/Capabilities/Full"
            response = requests.post(
                url, headers=self._headers(access_token, user_id), json=capabilities
            )
            response.raise_for_status()
            self.logger.info("Registered device capabilities with Emby")
        except Exception as e:
            self.logger.warning(f"Failed to register device capabilities: {e}")

    # =========================================================================
    # Library navigation
    # =========================================================================

    def get_libraries(self, access_token=None, user_id=None):
        """Get media libraries accessible to the given user.

        Without user_id, falls back to /emby/Library/MediaFolders using
        the admin api_key.
        """
        try:
            if user_id:
                url = f"{self.server_url}/emby/Users/{user_id}/Views"
            else:
                url = f"{self.server_url}/emby/Library/MediaFolders"
            response = requests.get(url, headers=self._headers(access_token, user_id))
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Error fetching libraries: {e}")
            return {"Items": []}

    def _ensure_library_cache(self, access_token=None, user_id=None):
        """Populate library_id -> CollectionType cache per user.

        Used by get_items() so folder-organised libraries return their
        Movies / Series directly rather than raw Folder entries.
        """
        cache_key = user_id or "_anon_"
        if cache_key in self._library_collection_types:
            return
        try:
            libs = self.get_libraries(access_token, user_id).get("Items", [])
            cache = {}
            for lib in libs:
                lib_id = lib.get("Id")
                if lib_id:
                    cache[lib_id] = lib.get("CollectionType")
            self._library_collection_types[cache_key] = cache
        except Exception as e:
            self.logger.warning(f"Could not populate library cache: {e}")

    def get_items(self, parent_id=None, item_type=None, recursive=False,
                  start_index=None, limit=None,
                  access_token=None, user_id=None):
        """Get items from library.

        When parent_id refers to a top-level library (CollectionFolder),
        derive the right IncludeItemTypes and Recursive flags from the
        library's CollectionType so Emby resolves folder-organised
        content into the actual Movie / Series items.
        """
        try:
            effective_type = item_type
            effective_recursive = recursive
            if parent_id and not item_type and not recursive:
                self._ensure_library_cache(access_token, user_id)
                cache_key = user_id or "_anon_"
                user_cache = self._library_collection_types.get(cache_key, {})
                collection_type = user_cache.get(parent_id)
                if collection_type == "movies":
                    effective_type = "Movie"
                    effective_recursive = True
                elif collection_type == "tvshows":
                    effective_type = "Series"
                    effective_recursive = False
                elif collection_type == "boxsets":
                    effective_type = "BoxSet"
                    effective_recursive = False
                elif collection_type == "music":
                    effective_type = "MusicArtist"
                    effective_recursive = False
                elif collection_type == "homevideos" or collection_type == "photos":
                    effective_type = "Movie,Video,Photo"
                    effective_recursive = True

            if user_id:
                url = f"{self.server_url}/emby/Users/{user_id}/Items"
            else:
                url = f"{self.server_url}/emby/Items"
            params = {
                "Recursive": str(effective_recursive).lower(),
                "Fields": "Overview,PrimaryImageAspectRatio,ProductionYear,IndexNumber,ParentIndexNumber,SeriesId,SeasonId",
                # SortName strips leading articles ("The Matrix" sorts
                # under M, "An Inconvenient Truth" under I), so the
                # frontend A-Z jump bar lands on the letter the user
                # would actually look under. Doing this at the Emby
                # query layer keeps pagination consistent with the
                # display order (a client-side re-sort would scramble
                # page boundaries).
                "SortBy": "SortName",
                "SortOrder": "Ascending",
            }

            if parent_id:
                params["ParentId"] = parent_id
            if effective_type:
                params["IncludeItemTypes"] = effective_type
            if start_index is not None:
                params["StartIndex"] = start_index
            if limit is not None:
                params["Limit"] = limit

            response = requests.get(
                url, headers=self._headers(access_token, user_id), params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Error fetching items: {e}")
            return {"Items": [], "TotalRecordCount": 0}

    def get_item_details(self, item_id, access_token=None, user_id=None):
        """Get detailed information about a specific item."""
        if not user_id:
            self.logger.warning("No user_id for item details; cannot scope request")
            return None
        try:
            url = f"{self.server_url}/emby/Users/{user_id}/Items/{item_id}"
            params = {"api_key": self._auth_param(access_token)}
            response = requests.get(
                url, headers=self._headers(access_token, user_id), params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                try:
                    url = f"{self.server_url}/emby/Items/{item_id}"
                    params = {"api_key": self._auth_param(access_token)}
                    response = requests.get(
                        url, headers=self._headers(access_token, user_id), params=params
                    )
                    response.raise_for_status()
                    return response.json()
                except Exception as e2:
                    self.logger.error(f"Item details fallback failed: {e2}")
            self.logger.error(f"Error fetching item details: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching item details: {e}")
            return None

    def search_items(self, query, access_token=None, user_id=None):
        """Search for items by name."""
        if not user_id:
            self.logger.warning("No user_id for search; cannot scope request")
            return {"Items": []}
        try:
            url = f"{self.server_url}/emby/Users/{user_id}/Items"
            params = {
                "SearchTerm": query,
                "Recursive": "true",
                "Fields": "Overview,PrimaryImageAspectRatio,ProductionYear",
                "IncludeItemTypes": "Movie,Series",
                "api_key": self._auth_param(access_token),
            }
            response = requests.get(
                url, headers=self._headers(access_token, user_id), params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Error searching items: {e}")
            return {"Items": []}

    def get_image_url(self, item_id, image_type="Primary", access_token=None):
        """Build an image URL with an api_key. Images are usually unscoped."""
        return (
            f"{self.server_url}/emby/Items/{item_id}/Images/{image_type}"
            f"?api_key={self._auth_param(access_token)}"
        )

    # =========================================================================
    # Playback
    # =========================================================================

    def get_playback_info(self, item_id, audio_index=None, subtitle_index=None,
                          media_source_id=None, max_streaming_bitrate=None,
                          start_time_ticks=None,
                          access_token=None, user_id=None):
        """Get playback information including MediaSourceId and PlaySessionId."""
        if not user_id:
            self.logger.warning("No user_id for playback info; cannot scope request")
            return None

        try:
            url = f"{self.server_url}/emby/Items/{item_id}/PlaybackInfo"
            params = {
                "UserId": user_id,
                "api_key": self._auth_param(access_token),
                "IsPlayback": "true",
                "AutoOpenLiveStream": "true",
                "StartTimeTicks": start_time_ticks or 0,
            }
            if max_streaming_bitrate:
                params["MaxStreamingBitrate"] = max_streaming_bitrate
            if audio_index is not None:
                params["AudioStreamIndex"] = audio_index
            if subtitle_index is not None:
                params["SubtitleStreamIndex"] = subtitle_index
            if media_source_id:
                params["MediaSourceId"] = media_source_id

            response = requests.post(
                url, headers=self._headers(access_token, user_id),
                params=params, json={},
            )
            response.raise_for_status()
            data = response.json()

            if data and "MediaSources" in data and data["MediaSources"]:
                media_source = data["MediaSources"][0]
                self.logger.debug(
                    f"PlaybackInfo - MediaSourceId: {media_source.get('Id')}, "
                    f"PlaySessionId: {data.get('PlaySessionId')}"
                )

            return data
        except Exception as e:
            self.logger.error(f"Error fetching playback info: {e}")
            return self.get_item_details(item_id, access_token=access_token, user_id=user_id)

    def stop_active_encodings(self, play_session_id=None, access_token=None):
        """Stop active HLS transcoding sessions for this device."""
        try:
            url = f"{self.server_url}/emby/Videos/ActiveEncodings"
            params = {
                "DeviceId": self.device_id,
                "api_key": self._auth_param(access_token),
            }
            if play_session_id:
                params["PlaySessionId"] = play_session_id
            response = requests.delete(
                url, headers=self._headers(access_token), params=params
            )
            response.raise_for_status()
            if play_session_id:
                self.logger.info(f"Stopped encoding for session {play_session_id}")
            else:
                self.logger.info(
                    f"Stopped all active encodings for device {self.device_id}"
                )
            return True
        except Exception as e:
            self.logger.warning(f"Failed to stop active encodings: {e}")
            return False

    # =========================================================================
    # Playback Progress Reporting
    # =========================================================================

    def _seconds_to_ticks(self, seconds):
        return int(seconds * 10_000_000)

    def _build_playback_payload(self, item_id, media_source_id, play_session_id,
                                position_seconds, is_paused, audio_index=None,
                                subtitle_index=None, run_time_seconds=None):
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

    def report_playback_start(self, item_id, media_source_id, play_session_id,
                              position_seconds=0, audio_index=None,
                              subtitle_index=None, run_time_seconds=None,
                              access_token=None, user_id=None):
        try:
            url = f"{self.server_url}/emby/Sessions/Playing"
            payload = self._build_playback_payload(
                item_id, media_source_id, play_session_id,
                position_seconds, is_paused=False,
                audio_index=audio_index, subtitle_index=subtitle_index,
                run_time_seconds=run_time_seconds
            )
            response = requests.post(
                url, headers=self._headers(access_token, user_id), json=payload
            )
            response.raise_for_status()
            self.logger.info(
                f"Reported playback start for item {item_id} at {position_seconds:.1f}s"
            )
            return True
        except Exception as e:
            self.logger.warning(f"Failed to report playback start: {e}")
            return False

    def report_playback_progress(self, item_id, media_source_id, play_session_id,
                                 position_seconds, is_paused, event_name="TimeUpdate",
                                 audio_index=None, subtitle_index=None,
                                 run_time_seconds=None,
                                 access_token=None, user_id=None):
        try:
            url = f"{self.server_url}/emby/Sessions/Playing/Progress"
            payload = self._build_playback_payload(
                item_id, media_source_id, play_session_id,
                position_seconds, is_paused,
                audio_index=audio_index, subtitle_index=subtitle_index,
                run_time_seconds=run_time_seconds
            )
            payload["EventName"] = event_name
            response = requests.post(
                url, headers=self._headers(access_token, user_id), json=payload
            )
            response.raise_for_status()
            self.logger.debug(
                f"Reported playback progress: {event_name} at "
                f"{position_seconds:.1f}s (paused={is_paused})"
            )
            return True
        except Exception as e:
            self.logger.warning(f"Failed to report playback progress: {e}")
            return False

    def report_playback_stopped(self, item_id, media_source_id, play_session_id,
                                position_seconds, run_time_seconds=None,
                                access_token=None, user_id=None):
        try:
            url = f"{self.server_url}/emby/Sessions/Playing/Stopped"
            payload = {
                "ItemId": item_id,
                "MediaSourceId": media_source_id,
                "PlaySessionId": play_session_id,
                "PositionTicks": self._seconds_to_ticks(position_seconds),
            }
            if run_time_seconds is not None:
                payload["RunTimeTicks"] = self._seconds_to_ticks(run_time_seconds)
            response = requests.post(
                url, headers=self._headers(access_token, user_id), json=payload
            )
            response.raise_for_status()
            self.logger.info(
                f"Reported playback stopped for item {item_id} at {position_seconds:.1f}s"
            )
            return True
        except Exception as e:
            self.logger.warning(f"Failed to report playback stopped: {e}")
            return False
