"""
Emby Client Module
Handles all interactions with the Emby Server API
"""

import requests
import secrets


class EmbyClient:
    """Client for interacting with Emby Server API"""

    def __init__(self, server_url, api_key, logger, username=None, password=None):
        """
        Initialize Emby client with server connection details.

        Args:
            server_url: Base URL of the Emby server
            api_key: API key for Emby authentication
            logger: Logger instance for logging
            username: Optional username for user-specific authentication
            password: Optional password for user-specific authentication
        """
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.logger = logger
        self.headers = {"X-Emby-Token": api_key, "Content-Type": "application/json"}
        self.user_id = None
        self.access_token = None
        self.device_id = "emby-watchparty-" + secrets.token_hex(8)

        # If username/password provided, authenticate as that user
        if username and password:
            self._authenticate_user(username, password)
        else:
            self._fetch_user_id()

    def _authenticate_user(self, username, password):
        """Authenticate as a specific user and get access token"""
        try:
            url = f"{self.server_url}/emby/Users/AuthenticateByName"
            headers = {
                "Content-Type": "application/json",
                "X-Emby-Authorization": f'Emby Client="WatchParty", Device="Web", DeviceId="{self.device_id}", Version="1.0"',
            }
            payload = {"Username": username, "Pw": password}

            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            # Extract access token and user ID
            self.access_token = data.get("AccessToken")
            self.user_id = data.get("User", {}).get("Id")

            # Update headers to use access token
            if self.access_token:
                self.api_key = self.access_token
                self.headers = {
                    "X-Emby-Token": self.access_token,
                    "Content-Type": "application/json",
                    "X-Emby-Authorization": f'Emby UserId="{self.user_id}", Client="WatchParty", Device="Web", DeviceId="{self.device_id}", Version="1.0", Token="{self.access_token}"',
                }

            self.logger.info(
                f"Authenticated as user: {data.get('User', {}).get('Name', 'Unknown')} (ID: {self.user_id})"
            )
            self.logger.debug(
                f"Access Token: {self.access_token[:20]}..."
                if self.access_token
                else "No access token"
            )

        except Exception as e:
            self.logger.error(f"Error authenticating user: {e}")
            self.logger.warning("Falling back to API key authentication")
            self._fetch_user_id()

    def _fetch_user_id(self):
        """Fetch a user ID to use for API calls that require user context"""
        try:
            # Get list of users
            url = f"{self.server_url}/emby/Users"
            params = {"api_key": self.api_key}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            users = response.json()

            if users and len(users) > 0:
                # Use the first user (usually the admin)
                self.user_id = users[0]["Id"]
                self.logger.info(
                    f"Using Emby user: {users[0].get('Name', 'Unknown')} (ID: {self.user_id})"
                )
            else:
                self.logger.warning("No Emby users found, some features may not work")
        except Exception as e:
            self.logger.error(f"Error fetching user ID: {e}")
            self.logger.warning("Some API features may not work without user context")

    def get_libraries(self):
        """Get media libraries accessible to the authenticated user"""
        try:
            # Use user-specific endpoint to only get libraries the user has access to
            if self.user_id:
                url = f"{self.server_url}/emby/Users/{self.user_id}/Views"
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                return response.json()
            else:
                # Fallback to all media folders if no user context
                url = f"{self.server_url}/emby/Library/MediaFolders"
                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            self.logger.error(f"Error fetching libraries: {e}")
            return {"Items": []}

    def get_items(self, parent_id=None, item_type=None, recursive=False, start_index=None, limit=None):
        """Get items from library"""
        try:
            url = f"{self.server_url}/emby/Items"
            params = {
                "Recursive": str(recursive).lower(),
                "Fields": "Overview,PrimaryImageAspectRatio,ProductionYear,IndexNumber,ParentIndexNumber,SeriesId,SeasonId",
            }

            if parent_id:
                params["ParentId"] = parent_id

            if item_type:
                params["IncludeItemTypes"] = item_type

            if start_index is not None:
                params["StartIndex"] = start_index

            if limit is not None:
                params["Limit"] = limit

            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Error fetching items: {e}")
            return {"Items": [], "TotalRecordCount": 0}

    def get_item_details(self, item_id):
        """Get detailed information about a specific item"""
        if not self.user_id:
            self.logger.warning("No user ID available for item details request")
            return None

        try:
            # Use user-specific endpoint which is more reliable
            url = f"{self.server_url}/emby/Users/{self.user_id}/Items/{item_id}"
            params = {"api_key": self.api_key}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # Try direct Items endpoint as fallback
                try:
                    url = f"{self.server_url}/emby/Items/{item_id}"
                    params = {"api_key": self.api_key}
                    response = requests.get(url, headers=self.headers, params=params)
                    response.raise_for_status()
                    return response.json()
                except Exception as e2:
                    self.logger.error(
                        f"Error fetching item details from Items endpoint: {e2}"
                    )
            self.logger.error(f"Error fetching item details: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching item details: {e}")
            return None

    def search_items(self, query):
        """Search for items by name"""
        if not self.user_id:
            self.logger.warning("No user ID available for search request")
            return {"Items": []}

        try:
            url = f"{self.server_url}/emby/Users/{self.user_id}/Items"
            params = {
                "SearchTerm": query,
                "Recursive": "true",
                "Fields": "Overview,PrimaryImageAspectRatio,ProductionYear",
                "IncludeItemTypes": "Movie,Series",
                "api_key": self.api_key,
            }
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Error searching items: {e}")
            return {"Items": []}

    def get_image_url(self, item_id, image_type="Primary"):
        """Get image URL for an item"""
        return f"{self.server_url}/emby/Items/{item_id}/Images/{image_type}?api_key={self.api_key}"

    def get_playback_info(self, item_id):
        """Get playback information including MediaSourceId and PlaySessionId"""
        if not self.user_id:
            self.logger.warning("No user ID available for playback info request")
            return None

        try:
            # Use POST request to PlaybackInfo endpoint as per Emby API
            url = f"{self.server_url}/emby/Items/{item_id}/PlaybackInfo"
            params = {"UserId": self.user_id, "api_key": self.api_key}
            response = requests.post(url, headers=self.headers, params=params, json={})
            response.raise_for_status()
            data = response.json()

            # Extract important info
            if data and "MediaSources" in data and data["MediaSources"]:
                media_source = data["MediaSources"][0]
                self.logger.debug(
                    f"PlaybackInfo - MediaSourceId: {media_source.get('Id')}, PlaySessionId: {data.get('PlaySessionId')}"
                )

            return data
        except Exception as e:
            self.logger.error(f"Error fetching playback info: {e}")
            # Fallback to trying to get item details which may have MediaStreams
            return self.get_item_details(item_id)

    def stop_active_encodings(self):
        """
        Stop all active HLS transcoding sessions for this device.
        Should be called when playback stops to free up server resources.

        Per Emby API: After playback is complete, it is necessary to inform
        the server to stop any related HLS transcoding.
        """
        try:
            url = f"{self.server_url}/emby/Videos/ActiveEncodings"
            params = {"DeviceId": self.device_id, "api_key": self.api_key}
            response = requests.delete(url, headers=self.headers, params=params)
            response.raise_for_status()
            self.logger.info(f"Stopped active encodings for device {self.device_id}")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to stop active encodings: {e}")
            return False

    # =========================================================================
    # Playback Progress Reporting
    # =========================================================================

    def _seconds_to_ticks(self, seconds):
        """Convert seconds to Emby ticks (100-nanosecond intervals)"""
        return int(seconds * 10_000_000)

    def _build_playback_payload(self, item_id, media_source_id, play_session_id,
                                  position_seconds, is_paused, audio_index=None,
                                  subtitle_index=None, run_time_seconds=None):
        """Build the common payload for playback reporting"""
        payload = {
            "ItemId": item_id,
            "MediaSourceId": media_source_id,
            "PlaySessionId": play_session_id,
            "PositionTicks": self._seconds_to_ticks(position_seconds),
            "IsPaused": is_paused,
            "CanSeek": True,
            "PlayMethod": "Transcode",  # Watch party always uses HLS transcoding
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
                               subtitle_index=None, run_time_seconds=None):
        """
        Report playback start to Emby server.
        Call this when a video begins playing.

        Args:
            item_id: Emby item ID
            media_source_id: Media source ID from PlaybackInfo
            play_session_id: Play session ID from PlaybackInfo
            position_seconds: Starting position in seconds (default 0)
            audio_index: Selected audio stream index
            subtitle_index: Selected subtitle stream index (-1 for none)
            run_time_seconds: Total runtime in seconds
        """
        try:
            url = f"{self.server_url}/emby/Sessions/Playing"
            payload = self._build_playback_payload(
                item_id, media_source_id, play_session_id,
                position_seconds, is_paused=False,
                audio_index=audio_index, subtitle_index=subtitle_index,
                run_time_seconds=run_time_seconds
            )

            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            self.logger.info(f"Reported playback start for item {item_id} at {position_seconds:.1f}s")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to report playback start: {e}")
            return False

    def report_playback_progress(self, item_id, media_source_id, play_session_id,
                                  position_seconds, is_paused, event_name="TimeUpdate",
                                  audio_index=None, subtitle_index=None,
                                  run_time_seconds=None):
        """
        Report playback progress to Emby server.
        Call this periodically during playback and on play/pause/seek events.

        Args:
            item_id: Emby item ID
            media_source_id: Media source ID from PlaybackInfo
            play_session_id: Play session ID from PlaybackInfo
            position_seconds: Current position in seconds
            is_paused: Whether playback is paused
            event_name: Event type - "TimeUpdate", "Pause", "Unpause", "AudioTrackChange", "SubtitleTrackChange"
            audio_index: Selected audio stream index
            subtitle_index: Selected subtitle stream index (-1 for none)
            run_time_seconds: Total runtime in seconds
        """
        try:
            url = f"{self.server_url}/emby/Sessions/Playing/Progress"
            payload = self._build_playback_payload(
                item_id, media_source_id, play_session_id,
                position_seconds, is_paused,
                audio_index=audio_index, subtitle_index=subtitle_index,
                run_time_seconds=run_time_seconds
            )
            payload["EventName"] = event_name

            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            self.logger.debug(f"Reported playback progress: {event_name} at {position_seconds:.1f}s (paused={is_paused})")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to report playback progress: {e}")
            return False

    def report_playback_stopped(self, item_id, media_source_id, play_session_id,
                                 position_seconds, run_time_seconds=None):
        """
        Report playback stopped to Emby server.
        Call this when playback ends or is stopped.

        Args:
            item_id: Emby item ID
            media_source_id: Media source ID from PlaybackInfo
            play_session_id: Play session ID from PlaybackInfo
            position_seconds: Final position in seconds
            run_time_seconds: Total runtime in seconds
        """
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

            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            self.logger.info(f"Reported playback stopped for item {item_id} at {position_seconds:.1f}s")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to report playback stopped: {e}")
            return False
