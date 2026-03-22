"""Playback handlers: select_video, stop_video, change_streams, video_ended, report_progress"""

from datetime import datetime
from backend.src.stream_builder import QUALITY_PRESETS, DEFAULT_QUALITY, build_stream_params


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    config = ctx['config']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    token_manager = ctx['token_manager']

    @sio.on("select_video")
    async def handle_select_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        item_id = data.get("item_id")
        item_name = data.get("item_name", "Unknown")
        item_overview = data.get("item_overview", "")
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")

        if not party_manager.exists(party_id):
            await sio.emit("error", {"message": "Watch party not found"}, to=sid)
            return

        party = party_manager.get(party_id)

        playback_info = emby_client.get_playback_info(item_id)
        if not playback_info or "MediaSources" not in playback_info:
            await sio.emit("error", {"message": "Failed to load video"}, to=sid)
            return

        media_source = playback_info["MediaSources"][0]
        media_source_id = media_source["Id"]
        play_session_id = playback_info.get("PlaySessionId")

        # Default audio track
        if audio_index is None and "MediaStreams" in media_source:
            for stream in media_source["MediaStreams"]:
                if stream.get("Type") == "Audio" and stream.get("IsDefault"):
                    audio_index = stream.get("Index")
                    break
            if audio_index is None:
                for stream in media_source["MediaStreams"]:
                    if stream.get("Type") == "Audio":
                        audio_index = stream.get("Index")
                        break

        quality = data.get("quality")
        if not quality or quality not in QUALITY_PRESETS:
            quality = DEFAULT_QUALITY

        params = build_stream_params(
            emby_client, media_source, media_source_id, play_session_id,
            audio_index, subtitle_index, quality, logger,
        )
        app_prefix = config.APP_PREFIX
        stream_url_base = f"{app_prefix}/hls/{item_id}/master.m3u8?{'&'.join(params)}"

        # Stop previous video
        if party.get("current_video") and party["current_video"].get("play_session_id"):
            prev = party["current_video"]
            prev_time = party["playback_state"].get("time", 0)
            emby_client.report_playback_stopped(
                item_id=prev["item_id"], media_source_id=prev["media_source_id"],
                play_session_id=prev["play_session_id"], position_seconds=prev_time,
                run_time_seconds=prev.get("run_time_seconds"),
            )
            emby_client.stop_active_encodings()

        run_time_ticks = media_source.get("RunTimeTicks", 0)
        run_time_seconds = run_time_ticks / 10_000_000 if run_time_ticks else None

        party["current_video"] = {
            "item_id": item_id, "title": item_name, "overview": item_overview,
            "stream_url_base": stream_url_base, "audio_index": audio_index,
            "subtitle_index": subtitle_index, "media_source_id": media_source_id,
            "play_session_id": play_session_id, "run_time_seconds": run_time_seconds,
            "selected_by": sid, "quality": quality,
        }

        emby_client.report_playback_start(
            item_id=item_id, media_source_id=media_source_id,
            play_session_id=play_session_id, position_seconds=0,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=run_time_seconds,
        )

        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }

        # Send video to each user with individual token
        for user_sid in list(party["users"].keys()):
            username = party["users"][user_sid]
            stream_url = stream_url_base
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = token_manager.get_or_create(party_id, user_sid)
                if user_token:
                    stream_url += f"&token={user_token}"

            await sio.emit("video_selected", {
                "video": {
                    "item_id": item_id, "title": item_name, "overview": item_overview,
                    "stream_url": stream_url, "audio_index": audio_index,
                    "subtitle_index": subtitle_index, "media_source_id": media_source_id,
                    "selected_by": sid, "quality": quality,
                }
            }, to=user_sid)

    @sio.on("stop_video")
    async def handle_stop_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)

        if not party or not party.get("current_video"):
            return
        if party["current_video"].get("selected_by") != sid:
            await sio.emit("error", {"message": "Only the selector can stop the video"}, to=sid)
            return

        video_title = party["current_video"].get("title", "Unknown")
        username = party["users"].get(sid, "Unknown")
        current_video = party["current_video"]
        current_time = party["playback_state"].get("time", 0)

        if current_video.get("play_session_id"):
            emby_client.report_playback_stopped(
                item_id=current_video["item_id"],
                media_source_id=current_video["media_source_id"],
                play_session_id=current_video["play_session_id"],
                position_seconds=current_time,
                run_time_seconds=current_video.get("run_time_seconds"),
            )
        emby_client.stop_active_encodings()

        party["current_video"] = None
        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }

        await sio.emit("video_stopped", {
            "message": f"{username} stopped the video", "stopped_by": username,
        }, room=party_id)
        logger.info(f"User {username} stopped '{video_title}' in party {party_id}")

    @sio.on("change_streams")
    async def handle_change_streams(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")
        quality = data.get("quality")

        party = party_manager.get(party_id)
        if not party or not party.get("current_video"):
            return

        current_video = party["current_video"]
        item_id = current_video["item_id"]

        if not quality or quality not in QUALITY_PRESETS:
            quality = current_video.get("quality", DEFAULT_QUALITY)

        playback_info = emby_client.get_playback_info(item_id)
        if not playback_info or "MediaSources" not in playback_info:
            return

        media_source = playback_info["MediaSources"][0]
        media_source_id = media_source["Id"]
        play_session_id = playback_info.get("PlaySessionId")

        params = build_stream_params(
            emby_client, media_source, media_source_id, play_session_id,
            audio_index, subtitle_index, quality, logger,
        )
        app_prefix = config.APP_PREFIX
        stream_url_base = f"{app_prefix}/hls/{item_id}/master.m3u8?{'&'.join(params)}"

        # Stop old transcode
        if current_video.get("play_session_id"):
            current_time = party["playback_state"]["time"]
            emby_client.report_playback_stopped(
                item_id=item_id, media_source_id=current_video.get("media_source_id"),
                play_session_id=current_video["play_session_id"],
                position_seconds=current_time, run_time_seconds=current_video.get("run_time_seconds"),
            )

        current_video["stream_url_base"] = stream_url_base
        current_video["audio_index"] = audio_index
        current_video["subtitle_index"] = subtitle_index
        current_video["media_source_id"] = media_source_id
        current_video["play_session_id"] = play_session_id
        current_video["quality"] = quality

        current_time = party["playback_state"]["time"]
        emby_client.report_playback_start(
            item_id=item_id, media_source_id=media_source_id,
            play_session_id=play_session_id, position_seconds=current_time,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds"),
        )

        for user_sid in list(party["users"].keys()):
            stream_url = stream_url_base
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = token_manager.get_or_create(party_id, user_sid)
                if user_token:
                    stream_url += f"&token={user_token}"
            await sio.emit("streams_changed", {
                "video": {
                    "item_id": item_id, "title": current_video["title"],
                    "overview": current_video["overview"], "stream_url": stream_url,
                    "audio_index": audio_index, "subtitle_index": subtitle_index,
                    "media_source_id": media_source_id,
                    "selected_by": current_video.get("selected_by"), "quality": quality,
                },
                "current_time": current_time,
            }, to=user_sid)

    @sio.on("video_ended")
    async def handle_video_ended(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        logger.info(f"Video ended in party {party_id}")
        current_video = party.get("current_video")
        if current_video and current_video.get("play_session_id"):
            final_pos = current_video.get("run_time_seconds", 0)
            emby_client.report_playback_stopped(
                item_id=current_video["item_id"],
                media_source_id=current_video["media_source_id"],
                play_session_id=current_video["play_session_id"],
                position_seconds=final_pos,
                run_time_seconds=current_video.get("run_time_seconds"),
            )

        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }
        await sio.emit("video_ended", {
            "party_id": party_id, "timestamp": datetime.now().isoformat(),
        }, room=party_id)

    @sio.on("report_progress")
    async def handle_report_progress(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party:
            return

        current_video = party.get("current_video")
        if not current_video or not current_video.get("play_session_id"):
            return
        if current_video.get("selected_by") != sid:
            return

        party["playback_state"]["time"] = current_time
        party["playback_state"]["last_update"] = datetime.now().isoformat()

        is_playing = party["playback_state"].get("playing", False)
        emby_client.report_playback_progress(
            item_id=current_video["item_id"],
            media_source_id=current_video["media_source_id"],
            play_session_id=current_video["play_session_id"],
            position_seconds=current_time, is_paused=not is_playing, event_name="TimeUpdate",
            audio_index=current_video.get("audio_index"),
            subtitle_index=current_video.get("subtitle_index") if current_video.get("subtitle_index") != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds"),
        )
