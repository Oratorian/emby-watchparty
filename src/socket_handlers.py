"""
SocketIO Event Handlers Module
All WebSocket event handlers for real-time communication
"""

from flask_socketio import emit, join_room, leave_room, rooms
from flask import request
from datetime import datetime
import time
import requests

from src import __version__


QUALITY_PRESETS = {
    "1080p-high": {"max_width": 1920, "max_height": 1080, "bitrate": 10_000_000, "label": "1080p (10 Mbps)"},
    "1080p":      {"max_width": 1920, "max_height": 1080, "bitrate": 8_000_000,  "label": "1080p (8 Mbps)"},
    "720p":       {"max_width": 1280, "max_height": 720,  "bitrate": 4_000_000,  "label": "720p (4 Mbps)"},
    "480p":       {"max_width": 854,  "max_height": 480,  "bitrate": 1_500_000,  "label": "480p (1.5 Mbps)"},
    "360p":       {"max_width": 640,  "max_height": 360,  "bitrate": 500_000,    "label": "360p (0.5 Mbps)"},
}
DEFAULT_QUALITY = "1080p-high"


def build_stream_params(emby_client, media_source, media_source_id, play_session_id,
                        audio_index, subtitle_index, quality, logger):
    """
    Build HLS stream URL parameters for Emby.

    Args:
        emby_client: EmbyClient instance (for device_id, api_key)
        media_source: MediaSource dict from Emby PlaybackInfo
        media_source_id: MediaSource ID string
        play_session_id: PlaySession ID string
        audio_index: Audio stream index (int or None)
        subtitle_index: Subtitle stream index (int or None)
        quality: Quality preset key (e.g. "1080p", "720p")
        logger: Logger instance

    Returns:
        list of URL parameter strings
    """
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])
    max_width = preset["max_width"]
    max_height = preset["max_height"]
    max_bitrate = preset["bitrate"]

    # Detect source video codec and bitrate
    source_video_codec = None
    source_video_bitrate = None
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            source_video_codec = (stream.get("Codec") or "").lower()
            source_video_bitrate = stream.get("BitRate")
            logger.info(f"Source video codec: {source_video_codec}, bitrate: {source_video_bitrate}")
            break

    params = [
        f"MediaSourceId={media_source_id}",
        f"PlaySessionId={play_session_id}",
        f"DeviceId={emby_client.device_id}",
        f"api_key={emby_client.api_key}",
        "SegmentContainer=ts",
        "TranscodingMaxAudioChannels=2",
        "AudioCodec=aac,mp3",
        "BreakOnNonKeyFrames=True",
        "MaxAudioChannels=2",
        f"MaxWidth={max_width}",
        f"MaxHeight={max_height}",
    ]

    # Determine if transcoding is needed
    source_width = None
    for stream in media_source.get("MediaStreams", []):
        if stream.get("Type") == "Video":
            source_width = stream.get("Width")
            break

    needs_downscale = source_width and source_width > max_width

    if source_video_codec != "h264" or needs_downscale:
        params.append("VideoCodec=h264")
        params.append(f"VideoBitrate={max_bitrate}")
        if source_video_codec != "h264":
            logger.info(f"Source is {source_video_codec}, transcoding to h264 at {preset['label']}")
        else:
            logger.info(f"Downscaling from {source_width}px to {max_width}px at {preset['label']}")
    elif source_video_bitrate and source_video_bitrate > max_bitrate:
        params.append("VideoCodec=h264")
        params.append(f"VideoBitrate={max_bitrate}")
        logger.info(f"Source is h264 but bitrate {source_video_bitrate // 1_000_000}Mbps exceeds cap, transcoding at {preset['label']}")
    else:
        logger.info(f"Source is h264 at {(source_video_bitrate or 0) // 1_000_000}Mbps, quality preset {preset['label']}")

    # Audio stream selection
    if audio_index is not None:
        params.append(f"AudioStreamIndex={audio_index}")
        logger.debug(f"Using audio stream index: {audio_index}")
    else:
        logger.debug("No audio stream index specified, Emby will use default")

    # Subtitle handling
    if subtitle_index is not None and subtitle_index != -1:
        is_pgs = False
        for stream in media_source["MediaStreams"]:
            if (
                stream.get("Type") == "Subtitle"
                and stream.get("Index") == subtitle_index
            ):
                codec = stream.get("Codec", "").lower()
                is_pgs = codec in [
                    "pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub",
                ]
                break

        if is_pgs:
            params.append(f"SubtitleStreamIndex={subtitle_index}")
            params.append("SubtitleMethod=Encode")
            logger.info(f"Burning in PGS subtitle track {subtitle_index}")
        else:
            logger.info(f"Text subtitle {subtitle_index} will be loaded separately as VTT")
    else:
        logger.debug("No subtitles selected - omitting subtitle parameters")

    return params


def init_socket_handlers(socketio, emby_client, party_manager, config, logger):
    """
    Initialize all SocketIO event handlers with dependency injection

    Args:
        socketio: SocketIO instance
        emby_client: EmbyClient instance
        party_manager: PartyManager instance
        config: Configuration module
        logger: Logger instance
    """

    # Import utils functions
    from src.utils import generate_random_username, generate_hls_token, get_user_token

    # Quick access to state
    watch_parties = party_manager.watch_parties
    hls_tokens = party_manager.hls_tokens

    @socketio.on("connect")
    def handle_connect():
        """Handle new WebSocket connection"""
        logger.info(f"Client connected: {request.sid}")
        emit("connected", {"sid": request.sid})

    @socketio.on("disconnect")
    def handle_disconnect():
        """Handle WebSocket disconnection"""
        logger.info(f"Client disconnected: {request.sid}")

        # Remove user from all watch parties
        for party_id, party in watch_parties.items():
            if request.sid in party["users"]:
                username = party["users"][request.sid]
                del party["users"][request.sid]
                emit(
                    "user_left",
                    {"username": username, "users": list(party["users"].values())},
                    room=party_id,
                    skip_sid=request.sid,
                )

    @socketio.on("join_party")
    def handle_join_party(data):
        """User joins a watch party"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        username = data.get("username", "").strip()

        # Generate random username if empty
        if not username:
            username = generate_random_username()
            logger.info(f"Generated random username: {username}")

        if party_id not in watch_parties:
            logger.warning(f"Join failed: party {party_id} not found (user: {username})")
            emit("error", {"message": "Watch party not found"})
            return

        # Evict stale SID if same username is already in the party (e.g. page refresh)
        old_sid = None
        for sid, existing_username in list(watch_parties[party_id]["users"].items()):
            if existing_username == username and sid != request.sid:
                old_sid = sid
                del watch_parties[party_id]["users"][sid]
                leave_room(party_id, sid=sid)
                logger.info(
                    f"Evicted stale session {sid} for user {username} in party {party_id}"
                )
                # Transfer video control so refreshed user can still stop/report progress
                if (
                    watch_parties[party_id]["current_video"]
                    and watch_parties[party_id]["current_video"].get("selected_by") == sid
                ):
                    watch_parties[party_id]["current_video"]["selected_by"] = request.sid
                break

        # Check max users per party limit (skip if this is a rejoin)
        if config.MAX_USERS_PER_PARTY > 0 and old_sid is None:
            current_user_count = len(watch_parties[party_id]["users"])
            if current_user_count >= config.MAX_USERS_PER_PARTY:
                logger.warning(
                    f"Party {party_id} is full ({current_user_count}/{config.MAX_USERS_PER_PARTY})"
                )
                emit(
                    "error",
                    {
                        "message": f"Party is full (max {config.MAX_USERS_PER_PARTY} users)"
                    },
                )
                return

        # Join the room
        join_room(party_id)

        # Add user to party
        watch_parties[party_id]["users"][request.sid] = username

        # Notify everyone
        emit(
            "user_joined",
            {
                "username": username,
                "users": list(watch_parties[party_id]["users"].values()),
            },
            room=party_id,
        )

        # Send current state to the new user with their individual token
        party = watch_parties[party_id]
        current_video = None

        if party["current_video"]:
            # Build video object with individual token for this user
            current_video = {
                "item_id": party["current_video"]["item_id"],
                "title": party["current_video"]["title"],
                "overview": party["current_video"]["overview"],
                "audio_index": party["current_video"]["audio_index"],
                "subtitle_index": party["current_video"]["subtitle_index"],
                "media_source_id": party["current_video"].get("media_source_id"),
                "selected_by": party["current_video"].get("selected_by"),
                "quality": party["current_video"].get("quality", DEFAULT_QUALITY),
            }

            # Add stream URL with individual token
            stream_url = party["current_video"]["stream_url_base"]
            if config.ENABLE_HLS_TOKEN_VALIDATION == 'true':
                user_token = get_user_token(
                    party_id, request.sid, hls_tokens, config, logger
                )
                if user_token:
                    stream_url += f"&token={user_token}"
                    logger.debug(
                        f"New user {username} joining party {party_id} with token: {user_token[:16]}..."
                    )
                else:
                    logger.warning(
                        f"Failed to generate token for new user {username} in party {party_id}"
                    )

            current_video["stream_url"] = stream_url

        # Calculate accurate current time for new joiner
        playback_state = party["playback_state"].copy()
        if playback_state.get("playing") and playback_state.get("last_update"):
            try:
                # Calculate elapsed time since last update
                from datetime import datetime

                last_update = datetime.fromisoformat(playback_state["last_update"])
                elapsed_seconds = (datetime.now() - last_update).total_seconds()

                # Add elapsed time to stored time for accurate sync
                stored_time = playback_state["time"]
                current_time = stored_time + elapsed_seconds
                playback_state["time"] = current_time

                logger.debug(
                    f"New joiner sync: stored_time={stored_time:.2f}s, elapsed={elapsed_seconds:.2f}s, current_time={current_time:.2f}s"
                )
            except Exception as e:
                logger.warning(f"Error calculating playback time for new joiner: {e}")

        emit(
            "sync_state",
            {"current_video": current_video, "playback_state": playback_state},
        )

    @socketio.on("leave_party")
    def handle_leave_party(data):
        """User leaves a watch party"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching

        if (
            party_id in watch_parties
            and request.sid in watch_parties[party_id]["users"]
        ):
            username = watch_parties[party_id]["users"][request.sid]
            leave_room(party_id)
            del watch_parties[party_id]["users"][request.sid]

            emit(
                "user_left",
                {
                    "username": username,
                    "users": list(watch_parties[party_id]["users"].values()),
                },
                room=party_id,
            )

    @socketio.on("select_video")
    def handle_select_video(data):
        """Host selects a video to watch"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        item_id = data.get("item_id")
        item_name = data.get("item_name", "Unknown")
        item_overview = data.get("item_overview", "")
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")

        if party_id not in watch_parties:
            logger.warning(f"Video selection failed: party {party_id} not found")
            emit("error", {"message": "Watch party not found"})
            return

        # Get PlaybackInfo to get MediaSourceId and PlaySessionId
        playback_info = emby_client.get_playback_info(item_id)

        if playback_info and "MediaSources" in playback_info:
            media_source_id = playback_info["MediaSources"][0]["Id"]
            play_session_id = playback_info.get("PlaySessionId")
            media_source = playback_info["MediaSources"][0]

            # If no audio/subtitle specified, use defaults from media source
            if audio_index is None and "MediaStreams" in media_source:
                # First, try to find the default audio stream
                for stream in media_source["MediaStreams"]:
                    if stream.get("Type") == "Audio" and stream.get("IsDefault"):
                        audio_index = stream.get("Index")
                        logger.debug(f"Using default audio track: {audio_index}")
                        break

                # If no default found, use the first audio stream
                if audio_index is None:
                    for stream in media_source["MediaStreams"]:
                        if stream.get("Type") == "Audio":
                            audio_index = stream.get("Index")
                            logger.debug(
                                f"No default audio found, using first audio track: {audio_index}"
                            )
                            break

            # Don't auto-select default subtitles - let users opt-in
            # (Removed automatic default subtitle selection)

            # Build HLS stream URL using quality preset
            quality = data.get("quality")
            if not quality or quality not in QUALITY_PRESETS:
                quality = DEFAULT_QUALITY
            params = build_stream_params(
                emby_client, media_source, media_source_id, play_session_id,
                audio_index, subtitle_index, quality, logger
            )

            app_prefix = getattr(config, 'APP_PREFIX', '')
            stream_url_base = f"{app_prefix}/hls/{item_id}/master.m3u8?{'&'.join(params)}"
        else:
            logger.error(f"Could not get playback info for item {item_id}")
            emit("error", {"message": "Failed to load video"})
            return

        # Stop any active playback/transcoding for previous video (if changing videos)
        if watch_parties[party_id].get("current_video"):
            prev_video = watch_parties[party_id]["current_video"]
            if prev_video.get("play_session_id"):
                prev_time = watch_parties[party_id]["playback_state"].get("time", 0)
                emby_client.report_playback_stopped(
                    item_id=prev_video["item_id"],
                    media_source_id=prev_video["media_source_id"],
                    play_session_id=prev_video["play_session_id"],
                    position_seconds=prev_time,
                    run_time_seconds=prev_video.get("run_time_seconds")
                )
            emby_client.stop_active_encodings()

        # Get runtime in seconds from media source (RunTimeTicks is in 100-nanosecond units)
        run_time_ticks = media_source.get("RunTimeTicks", 0)
        run_time_seconds = run_time_ticks / 10_000_000 if run_time_ticks else None

        # Store base URL without token in party data
        watch_parties[party_id]["current_video"] = {
            "item_id": item_id,
            "title": item_name,
            "overview": item_overview,
            "stream_url_base": stream_url_base,  # Base URL without token
            "audio_index": audio_index,
            "subtitle_index": subtitle_index,
            "media_source_id": media_source_id,  # Needed for subtitle URLs
            "play_session_id": play_session_id,  # Needed for playback progress reporting
            "run_time_seconds": run_time_seconds,  # Total duration for progress reporting
            "selected_by": request.sid,  # Track who selected this video
            "quality": quality,  # Current quality preset
        }

        # Report playback start to Emby so progress is tracked
        emby_client.report_playback_start(
            item_id=item_id,
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            position_seconds=0,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=run_time_seconds
        )

        watch_parties[party_id]["playback_state"] = {
            "playing": False,
            "time": 0,
            "last_update": datetime.now().isoformat(),
        }

        # Send video to each user with their own individual token
        logger.info(
            f"Sending video to {len(watch_parties[party_id]['users'])} users in party {party_id}"
        )
        for user_sid in watch_parties[party_id]["users"].keys():
            username = watch_parties[party_id]["users"][user_sid]
            stream_url_with_token = stream_url_base

            # Add individual token for this user
            if config.ENABLE_HLS_TOKEN_VALIDATION == 'true':
                user_token = get_user_token(
                    party_id, user_sid, hls_tokens, config, logger
                )
                if user_token:
                    stream_url_with_token += f"&token={user_token}"
                    logger.info(
                        f"Assigned token {user_token[:16]}... to user {username} (sid={user_sid})"
                    )
                else:
                    logger.warning(
                        f"Failed to get token for user {username} (sid={user_sid})"
                    )
            else:
                logger.info(
                    f"Sending video to user {username} without token (validation disabled)"
                )

            logger.debug(f"Stream URL for {username}: {stream_url_with_token[:100]}...")

            # Send to this specific user with their token
            socketio.emit(
                "video_selected",
                {
                    "video": {
                        "item_id": item_id,
                        "title": item_name,
                        "overview": item_overview,
                        "stream_url": stream_url_with_token,  # With individual token
                        "audio_index": audio_index,
                        "subtitle_index": subtitle_index,
                        "media_source_id": media_source_id,  # Needed for subtitle URLs
                        "selected_by": request.sid,  # Track who selected this video
                        "quality": quality,
                    }
                },
                to=user_sid,
            )  # Send only to this user's socket

    @socketio.on("stop_video")
    def handle_stop_video(data):
        """
        Stop the currently playing video and clear it from the party.
        Only the user who selected the video can stop it.

        Args:
            data: {
                'party_id': str - The party ID
            }

        Emits:
            'video_stopped': Broadcast to all users in the party
            'error': If user is not authorized or party doesn't exist
        """
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching

        if not party_id or party_id not in watch_parties:
            logger.warning(f"Stop video failed: party {party_id} not found")
            emit("error", {"message": "Party not found"})
            return

        party = watch_parties[party_id]

        # Check if there's a current video
        if not party.get("current_video"):
            logger.warning(f"Stop video failed: no video playing in party {party_id}")
            emit("error", {"message": "No video is currently playing"})
            return

        # Check if the requester is the one who selected the video
        if party["current_video"].get("selected_by") != request.sid:
            emit(
                "error", {"message": "Only the user who selected the video can stop it"}
            )
            logger.warning(
                f"User {request.sid} tried to stop video in party {party_id} but was not authorized"
            )
            return

        # Clear the video and reset playback state
        video_title = party["current_video"].get("title", "Unknown")
        username = party["users"].get(request.sid, "Unknown")
        current_video = party["current_video"]
        current_time = party["playback_state"].get("time", 0)

        # Report playback stopped to Emby before clearing
        if current_video.get("play_session_id"):
            emby_client.report_playback_stopped(
                item_id=current_video["item_id"],
                media_source_id=current_video["media_source_id"],
                play_session_id=current_video["play_session_id"],
                position_seconds=current_time,
                run_time_seconds=current_video.get("run_time_seconds")
            )

        # Stop any active transcoding sessions on Emby server
        emby_client.stop_active_encodings()

        party["current_video"] = None
        party["playback_state"] = {
            "playing": False,
            "time": 0,
            "last_update": datetime.now().isoformat(),
        }

        # Broadcast to all users in the party
        emit(
            "video_stopped",
            {"message": f"{username} stopped the video", "stopped_by": username},
            room=party_id,
        )

        logger.info(
            f"User {username} stopped video '{video_title}' in party {party_id}"
        )

    @socketio.on("play")
    def handle_play(data):
        """Handle play command"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        current_time = data.get("time", 0)

        if party_id in watch_parties:
            watch_parties[party_id]["playback_state"] = {
                "playing": True,
                "time": current_time,
                "last_update": datetime.now().isoformat(),
            }

            # Report play (unpause) event to Emby
            current_video = watch_parties[party_id].get("current_video")
            if current_video and current_video.get("play_session_id"):
                emby_client.report_playback_progress(
                    item_id=current_video["item_id"],
                    media_source_id=current_video["media_source_id"],
                    play_session_id=current_video["play_session_id"],
                    position_seconds=current_time,
                    is_paused=False,
                    event_name="Unpause",
                    audio_index=current_video.get("audio_index"),
                    subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
                    run_time_seconds=current_video.get("run_time_seconds")
                )

            emit("play", {"time": current_time}, room=party_id, skip_sid=request.sid)

    @socketio.on("pause")
    def handle_pause(data):
        """Handle pause command"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        current_time = data.get("time", 0)

        if party_id in watch_parties:
            watch_parties[party_id]["playback_state"] = {
                "playing": False,
                "time": current_time,
                "last_update": datetime.now().isoformat(),
            }

            # Report pause event to Emby
            current_video = watch_parties[party_id].get("current_video")
            if current_video and current_video.get("play_session_id"):
                emby_client.report_playback_progress(
                    item_id=current_video["item_id"],
                    media_source_id=current_video["media_source_id"],
                    play_session_id=current_video["play_session_id"],
                    position_seconds=current_time,
                    is_paused=True,
                    event_name="Pause",
                    audio_index=current_video.get("audio_index"),
                    subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
                    run_time_seconds=current_video.get("run_time_seconds")
                )

            emit("pause", {"time": current_time}, room=party_id, skip_sid=request.sid)

    @socketio.on("seek")
    def handle_seek(data):
        """Handle seek command with force pause for better buffering"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        seek_time = data.get("time", 0)

        if party_id in watch_parties:
            # Get current playing state before seek
            was_playing = watch_parties[party_id]["playback_state"].get(
                "playing", False
            )

            # Update playback state
            watch_parties[party_id]["playback_state"]["time"] = seek_time
            watch_parties[party_id]["playback_state"][
                "last_update"
            ] = datetime.now().isoformat()

            # Report seek (time update) to Emby
            current_video = watch_parties[party_id].get("current_video")
            if current_video and current_video.get("play_session_id"):
                emby_client.report_playback_progress(
                    item_id=current_video["item_id"],
                    media_source_id=current_video["media_source_id"],
                    play_session_id=current_video["play_session_id"],
                    position_seconds=seek_time,
                    is_paused=not was_playing,
                    event_name="TimeUpdate",
                    audio_index=current_video.get("audio_index"),
                    subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
                    run_time_seconds=current_video.get("run_time_seconds")
                )

            # If video was playing, force pause everyone (including seeker) for better buffering
            if was_playing:
                logger.info(
                    f"Seek during playback - pausing all clients (including seeker) first for buffering"
                )
                # First, pause everyone INCLUDING the seeking client
                emit("force_pause_before_seek", {"time": seek_time}, room=party_id)

                # Then send seek command with playing flag and longer buffer delay to ALL
                emit(
                    "seek",
                    {"time": seek_time, "playing": True, "buffer_delay": 1500},
                    room=party_id,
                )
            else:
                # Video was already paused, just seek normally for everyone
                emit("seek", {"time": seek_time, "playing": False}, room=party_id)

    @socketio.on("change_streams")
    def handle_change_streams(data):
        """Handle audio/subtitle/quality stream changes"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")
        quality = data.get("quality")

        if (
            party_id not in watch_parties
            or not watch_parties[party_id]["current_video"]
        ):
            logger.warning(f"Stream change requested but no video playing in party {party_id}")
            emit("error", {"message": "No video currently playing"})
            return

        current_video = watch_parties[party_id]["current_video"]
        item_id = current_video["item_id"]

        # Use provided quality or fall back to current party quality
        if not quality or quality not in QUALITY_PRESETS:
            quality = current_video.get("quality", DEFAULT_QUALITY)

        # Get PlaybackInfo for new stream parameters
        playback_info = emby_client.get_playback_info(item_id)

        if playback_info and "MediaSources" in playback_info:
            media_source_id = playback_info["MediaSources"][0]["Id"]
            play_session_id = playback_info.get("PlaySessionId")
            media_source = playback_info["MediaSources"][0]

            # Build HLS stream URL using quality preset
            params = build_stream_params(
                emby_client, media_source, media_source_id, play_session_id,
                audio_index, subtitle_index, quality, logger
            )

            app_prefix = getattr(config, 'APP_PREFIX', '')
            stream_url_base = f"{app_prefix}/hls/{item_id}/master.m3u8?{'&'.join(params)}"
        else:
            logger.error(f"Could not get playback info for item {item_id}")
            emit("error", {"message": "Failed to change streams"})
            return

        # Stop old transcode and report new playback session to Emby
        # This updates Emby's dashboard to show the current quality/bitrate
        old_play_session_id = current_video.get("play_session_id")
        if old_play_session_id:
            current_time = watch_parties[party_id]["playback_state"]["time"]
            emby_client.report_playback_stopped(
                item_id=item_id,
                media_source_id=current_video.get("media_source_id"),
                play_session_id=old_play_session_id,
                position_seconds=current_time,
                run_time_seconds=current_video.get("run_time_seconds")
            )

        # Update the video info with base URL (no token)
        current_video["stream_url_base"] = stream_url_base
        current_video["audio_index"] = audio_index
        current_video["subtitle_index"] = subtitle_index
        current_video["media_source_id"] = media_source_id
        current_video["play_session_id"] = play_session_id
        current_video["quality"] = quality

        # Report new playback start so Emby dashboard reflects current quality
        current_time = watch_parties[party_id]["playback_state"]["time"]
        emby_client.report_playback_start(
            item_id=item_id,
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            position_seconds=current_time,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds")
        )

        # Send stream change to each user with their individual token

        for user_sid in watch_parties[party_id]["users"].keys():
            stream_url_with_token = stream_url_base

            # Add individual token for this user
            if config.ENABLE_HLS_TOKEN_VALIDATION == 'true':
                user_token = get_user_token(
                    party_id, user_sid, hls_tokens, config, logger
                )
                if user_token:
                    stream_url_with_token += f"&token={user_token}"

            # Send to this specific user
            socketio.emit(
                "streams_changed",
                {
                    "video": {
                        "item_id": item_id,
                        "title": current_video["title"],
                        "overview": current_video["overview"],
                        "stream_url": stream_url_with_token,
                        "audio_index": audio_index,
                        "subtitle_index": subtitle_index,
                        "media_source_id": media_source_id,
                        "selected_by": current_video.get("selected_by"),
                        "quality": quality,
                    },
                    "current_time": current_time,
                },
                to=user_sid,
            )

    @socketio.on("chat_message")
    def handle_chat_message(data):
        """Handle chat messages"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        message = data.get("message", "")

        if (
            party_id in watch_parties
            and request.sid in watch_parties[party_id]["users"]
        ):
            username = watch_parties[party_id]["users"][request.sid]

            emit(
                "chat_message",
                {
                    "username": username,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                },
                room=party_id,
            )

    @socketio.on("video_ended")
    def handle_video_ended(data):
        """Handle video ended notification"""
        party_id = data.get("party_id", "").strip().upper()

        if party_id in watch_parties:
            logger.info(f"Video ended in party {party_id}")

            # Report playback stopped to Emby (video completed)
            current_video = watch_parties[party_id].get("current_video")
            if current_video and current_video.get("play_session_id"):
                # Use run_time_seconds as the final position (video completed)
                final_position = current_video.get("run_time_seconds", 0)
                emby_client.report_playback_stopped(
                    item_id=current_video["item_id"],
                    media_source_id=current_video["media_source_id"],
                    play_session_id=current_video["play_session_id"],
                    position_seconds=final_position,
                    run_time_seconds=current_video.get("run_time_seconds")
                )

            # Reset playback state to prevent position carry-over to next video
            watch_parties[party_id]["playback_state"] = {
                "playing": False,
                "time": 0,
                "last_update": datetime.now().isoformat(),
            }

            # Broadcast to all users in the party
            emit(
                "video_ended",
                {"party_id": party_id, "timestamp": datetime.now().isoformat()},
                room=party_id,
            )

    @socketio.on("report_progress")
    def handle_report_progress(data):
        """
        Handle periodic progress reports from the host client.
        Called every 10 seconds to report playback progress to Emby.
        Only the user who selected the video should call this.
        """
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)

        if party_id not in watch_parties:
            return

        party = watch_parties[party_id]
        current_video = party.get("current_video")

        # Only report if there's a video and it has a play session
        if not current_video or not current_video.get("play_session_id"):
            return

        # Only accept progress reports from the user who selected the video
        if current_video.get("selected_by") != request.sid:
            return

        # Update local playback state time
        party["playback_state"]["time"] = current_time
        party["playback_state"]["last_update"] = datetime.now().isoformat()

        # Report progress to Emby
        is_playing = party["playback_state"].get("playing", False)
        emby_client.report_playback_progress(
            item_id=current_video["item_id"],
            media_source_id=current_video["media_source_id"],
            play_session_id=current_video["play_session_id"],
            position_seconds=current_time,
            is_paused=not is_playing,
            event_name="TimeUpdate",
            audio_index=current_video.get("audio_index"),
            subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds")
        )

    @socketio.on("toggle_library")
    def handle_toggle_library(data):
        """Handle library sidebar toggle for all users"""
        party_id = data.get("party_id", "").strip().upper()
        show = data.get("show", False)

        if party_id in watch_parties:
            logger.info(f"Library toggled in party {party_id}: show={show}")

            # Broadcast to all users in the party
            emit("toggle_library", {"show": show}, room=party_id)


def check_for_updates(logger):
    """Check GitHub for latest release and notify if update available"""
    try:
        # GitHub API endpoint for latest release
        github_api_url = (
            "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
        )
        response = requests.get(github_api_url, timeout=5)

        if response.status_code == 200:
            latest_release = response.json()
            latest_version = latest_release.get("tag_name", "").lstrip("v")

            if latest_version and latest_version != __version__:
                logger.warning("=" * 60)
                logger.warning(
                    f"UPDATE AVAILABLE: v{latest_version} (current: v{__version__})"
                )
                logger.warning(
                    f"Download: {latest_release.get('html_url', 'https://github.com/Oratorian/emby-watchparty/releases')}"
                )
                logger.warning("=" * 60)
            else:
                logger.info(f"Running latest version: v{__version__}")
        else:
            # Silently skip if GitHub API is unreachable
            logger.debug(
                f"Could not check for updates (GitHub API returned {response.status_code})"
            )
    except Exception as e:
        # Don't spam logs if update check fails
        logger.debug(f"Update check failed: {e}")
