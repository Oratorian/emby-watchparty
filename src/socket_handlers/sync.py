"""
Playback Sync Handlers
Events: play, pause, seek
"""

from flask_socketio import emit
from flask import request
from datetime import datetime


def register(deps):
    socketio = deps['socketio']
    emby_client = deps['emby_client']
    logger = deps['logger']
    watch_parties = deps['watch_parties']

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

            username = watch_parties[party_id]["users"].get(request.sid, "Someone")
            emit("play", {"time": current_time, "username": username}, room=party_id, skip_sid=request.sid)

    @socketio.on("pause")
    def handle_pause(data):
        """Handle pause command"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        current_time = data.get("time", 0)

        if party_id in watch_parties:
            # Only the video selector can update server playback state
            current_video = watch_parties[party_id].get("current_video")
            if current_video and current_video.get("selected_by") != request.sid:
                username = watch_parties[party_id]["users"].get(request.sid, "Someone")
                logger.debug(f"Ignoring pause from {username} - not the selector")
                return

            watch_parties[party_id]["playback_state"] = {
                "playing": False,
                "time": current_time,
                "last_update": datetime.now().isoformat(),
            }

            # Report pause event to Emby
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

            username = watch_parties[party_id]["users"].get(request.sid, "Someone")
            emit("pause", {"time": current_time, "username": username}, room=party_id, skip_sid=request.sid)

    @socketio.on("seek")
    def handle_seek(data):
        """Handle seek command with force pause for better buffering"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        seek_time = data.get("time", 0)
        was_playing = data.get("was_playing", False)

        if party_id in watch_parties:
            # Only the video selector can update server playback state
            current_video = watch_parties[party_id].get("current_video")
            if current_video and current_video.get("selected_by") != request.sid:
                username = watch_parties[party_id]["users"].get(request.sid, "Someone")
                logger.debug(f"Ignoring seek from {username} - not the selector")
                return

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

            username = watch_parties[party_id]["users"].get(request.sid, "Someone")

            # If video was playing, force pause everyone (including seeker) for better buffering
            if was_playing:
                logger.info(
                    f"Seek during playback - pausing all clients (including seeker) first for buffering"
                )
                emit("force_pause_before_seek", {"time": seek_time}, room=party_id)

                emit(
                    "seek",
                    {"time": seek_time, "playing": True, "buffer_delay": 1500, "username": username},
                    room=party_id,
                )
            else:
                emit("seek", {"time": seek_time, "playing": False, "username": username}, room=party_id)
