"""Sync handlers: play, pause, seek"""

from datetime import datetime


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    logger = ctx['logger']
    party_manager = ctx['party_manager']

    @sio.on("play")
    async def handle_play(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party:
            return

        # Only the video selector can update server playback state
        current_video = party.get("current_video")
        if current_video and current_video.get("selected_by") != sid:
            username = party["users"].get(sid, "Someone")
            logger.debug(f"Ignoring play from {username} - not the selector")
            return

        party["playback_state"] = {
            "playing": True, "time": current_time,
            "last_update": datetime.now().isoformat(),
        }

        current_video = party.get("current_video")
        if current_video and current_video.get("play_session_id"):
            emby_client.report_playback_progress(
                item_id=current_video["item_id"],
                media_source_id=current_video["media_source_id"],
                play_session_id=current_video["play_session_id"],
                position_seconds=current_time, is_paused=False, event_name="Unpause",
                audio_index=current_video.get("audio_index"),
                subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
                run_time_seconds=current_video.get("run_time_seconds"),
            )

        username = party["users"].get(sid, "Someone")
        await sio.emit("play", {"time": current_time, "username": username},
                        room=party_id, skip_sid=sid)

    @sio.on("pause")
    async def handle_pause(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party:
            return

        # Only the video selector can update server playback state
        current_video = party.get("current_video")
        if current_video and current_video.get("selected_by") != sid:
            username = party["users"].get(sid, "Someone")
            logger.debug(f"Ignoring pause from {username} - not the selector")
            return

        party["playback_state"] = {
            "playing": False, "time": current_time,
            "last_update": datetime.now().isoformat(),
        }

        current_video = party.get("current_video")
        if current_video and current_video.get("play_session_id"):
            emby_client.report_playback_progress(
                item_id=current_video["item_id"],
                media_source_id=current_video["media_source_id"],
                play_session_id=current_video["play_session_id"],
                position_seconds=current_time, is_paused=True, event_name="Pause",
                audio_index=current_video.get("audio_index"),
                subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
                run_time_seconds=current_video.get("run_time_seconds"),
            )

        username = party["users"].get(sid, "Someone")
        await sio.emit("pause", {"time": current_time, "username": username},
                        room=party_id, skip_sid=sid)

    @sio.on("seek")
    async def handle_seek(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        seek_time = data.get("time", 0)
        was_playing = data.get("was_playing", False)
        party = party_manager.get(party_id)
        if not party:
            return

        # Only the video selector can update server playback state
        current_video = party.get("current_video")
        if current_video and current_video.get("selected_by") != sid:
            username = party["users"].get(sid, "Someone")
            logger.debug(f"Ignoring seek from {username} - not the selector")
            return

        party["playback_state"]["time"] = seek_time
        party["playback_state"]["last_update"] = datetime.now().isoformat()

        current_video = party.get("current_video")
        if current_video and current_video.get("play_session_id"):
            emby_client.report_playback_progress(
                item_id=current_video["item_id"],
                media_source_id=current_video["media_source_id"],
                play_session_id=current_video["play_session_id"],
                position_seconds=seek_time, is_paused=not was_playing, event_name="TimeUpdate",
                audio_index=current_video.get("audio_index"),
                subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
                run_time_seconds=current_video.get("run_time_seconds"),
            )

        username = party["users"].get(sid, "Someone")

        if was_playing:
            logger.info("Seek during playback - pausing all clients first for buffering")
            await sio.emit("force_pause_before_seek", {"time": seek_time}, room=party_id)
            await sio.emit("seek", {
                "time": seek_time, "playing": True, "buffer_delay": 1500, "username": username,
            }, room=party_id)
        else:
            await sio.emit("seek", {
                "time": seek_time, "playing": False, "username": username,
            }, room=party_id)
