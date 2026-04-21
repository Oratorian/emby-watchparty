"""
Playback Handlers
Events: select_video, stop_video, change_streams, video_ended, report_progress
"""

from flask_socketio import emit
from flask import request
from datetime import datetime

from src.socket_handlers.quality import QUALITY_PRESETS, DEFAULT_QUALITY, build_stream_params


def register(deps):
    socketio = deps['socketio']
    emby_client = deps['emby_client']
    config = deps['config']
    logger = deps['logger']
    watch_parties = deps['watch_parties']
    hls_tokens = deps['hls_tokens']
    get_user_token = deps['get_user_token']

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

        # Build HLS stream URL using quality preset
        quality = data.get("quality")
        if not quality or quality not in QUALITY_PRESETS:
            quality = DEFAULT_QUALITY
        preset = QUALITY_PRESETS[quality]

        # Get PlaybackInfo with Emby web client params for better
        # transcoding decisions and pre-started ffmpeg (AutoOpenLiveStream)
        playback_info = emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            max_streaming_bitrate=preset["bitrate"],
        )

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

        # Store base URL without token in party data.
        # selected_by tracks the current selector's sid; selected_by_username
        # survives reconnects so we can re-attach the selector role to the
        # same person after a disconnect rotates their sid (issue #28).
        selector_username = watch_parties[party_id]["users"].get(request.sid)
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
            "selected_by_username": selector_username,
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
        preset = QUALITY_PRESETS[quality]

        # Get PlaybackInfo with Emby web client params
        playback_info = emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            max_streaming_bitrate=preset["bitrate"],
        )

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
