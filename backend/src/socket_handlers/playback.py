"""Playback handlers: select_video, stop_video, change_streams, video_ended, report_progress, stream_ready.

Identity model:
- `current_video.selected_by` is the **client_id** of the user who picked
  the video, not their current sid. client_ids survive page refreshes,
  so a selector who reloads still owns Stop Video.
- Every Emby call uses the **host's** access_token / user_id. When the
  host has fully left (token cleared) Emby-touching events refuse the
  request; the party is LOCKED.
- After a video ends or is stopped in the PLAYING-ONLY state, the
  stored host token is wiped (full LOCKED).

See docs/AUTH-DESIGN.md.
"""

from datetime import datetime
from backend.src.stream_builder import QUALITY_PRESETS, DEFAULT_QUALITY


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    config = ctx['config']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    token_manager = ctx['token_manager']

    def _client_id_for_sid(party, sid):
        """Look up the persistent client_id mapped to this socket sid."""
        return party.get("sid_client_ids", {}).get(sid)

    def _host_creds(party):
        """Return (access_token, user_id) for the party's current host."""
        return party.get("host_access_token"), party.get("host_user_id")

    def _default_audio_index(media_source):
        """Find the default audio track index from a media source."""
        if "MediaStreams" not in media_source:
            return None
        for stream in media_source["MediaStreams"]:
            if stream.get("Type") == "Audio" and stream.get("IsDefault"):
                return stream.get("Index")
        for stream in media_source["MediaStreams"]:
            if stream.get("Type") == "Audio":
                return stream.get("Index")
        return None

    def _create_user_stream(party, party_id, sid, item_id, media_source,
                            audio_index, subtitle_index, quality, start_seconds=0):
        """Create a per-user Emby stream (own PlaySessionId and transcode).

        Returns the stream info dict, or None on failure.
        """
        access_token, user_id = _host_creds(party)
        start_ticks_for_info = int(start_seconds * 10_000_000) if start_seconds > 0 else 0
        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])
        playback_info = emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            max_streaming_bitrate=preset["bitrate"],
            start_time_ticks=start_ticks_for_info,
            access_token=access_token,
            user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            logger.error(f"Failed to get playback info for user stream (sid={sid})")
            return None

        user_media_source = playback_info["MediaSources"][0]
        media_source_id = user_media_source["Id"]
        play_session_id = playback_info.get("PlaySessionId")

        start_ticks = int(start_seconds * 10_000_000) if start_seconds > 0 else None

        from backend.src.stream_builder import StreamBuilder
        builder = StreamBuilder(emby_client, logger, config)
        stream_url_base = builder.build_stream_url(
            item_id=item_id,
            app_prefix=config.APP_PREFIX,
            media_source=user_media_source,
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            quality=quality,
            start_time_ticks=start_ticks,
        )

        stream_info = {
            "play_session_id": play_session_id,
            "media_source_id": media_source_id,
            "stream_url_base": stream_url_base,
            "audio_index": audio_index,
            "subtitle_index": subtitle_index,
            "quality": quality,
            "ready": False,
        }

        party.setdefault("user_streams", {})[sid] = stream_info

        run_time_seconds = party.get("current_video", {}).get("run_time_seconds")
        emby_client.report_playback_start(
            item_id=item_id, media_source_id=media_source_id,
            play_session_id=play_session_id, position_seconds=start_seconds,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=run_time_seconds,
            access_token=access_token,
            user_id=user_id,
        )

        logger.info(f"Created user stream for {party['users'].get(sid, sid)}: "
                     f"session={play_session_id}, start={start_seconds:.1f}s")
        return stream_info

    def _stop_user_stream(party, sid, position_seconds=0):
        """Stop a single user's Emby transcode and clean up."""
        user_streams = party.get("user_streams", {})
        stream = user_streams.pop(sid, None)
        if not stream or not stream.get("play_session_id"):
            return

        access_token, user_id = _host_creds(party)
        current_video = party.get("current_video")
        if current_video:
            emby_client.report_playback_stopped(
                item_id=current_video["item_id"],
                media_source_id=stream["media_source_id"],
                play_session_id=stream["play_session_id"],
                position_seconds=position_seconds,
                run_time_seconds=current_video.get("run_time_seconds"),
                access_token=access_token,
                user_id=user_id,
            )
        emby_client.stop_active_encodings(
            play_session_id=stream["play_session_id"],
            access_token=access_token,
        )

    def _stop_all_user_streams(party, position_seconds=0):
        """Stop all per-user transcodes."""
        for sid in list(party.get("user_streams", {}).keys()):
            _stop_user_stream(party, sid, position_seconds)

    def _wipe_host_if_orphan(party_id, party):
        """If host has already left and there's nothing left to play, wipe
        the stored token so the party fully transitions to LOCKED.
        """
        if party.get("host_left_at") is not None:
            party_manager.clear_host(party_id)
            logger.info(f"Party {party_id} -> LOCKED (host gone, playback ended)")

    def _start_ready_check(party, party_id):
        """Start a ready check for all users in the party."""
        expected = set(party["users"].keys())
        party["ready_check"] = {
            "active": True,
            "expected_sids": expected,
            "ready_sids": set(),
        }
        logger.debug(f"Ready check started for party {party_id}: expecting {len(expected)} users")

    async def _check_all_ready(party, party_id):
        """Check if all users are ready and emit all_ready if so."""
        rc = party.get("ready_check")
        if not rc or not rc.get("active"):
            return

        if rc["ready_sids"] >= rc["expected_sids"]:
            party["ready_check"] = None
            playback_state = party.get("playback_state", {})
            if playback_state.get("playing"):
                playback_state["last_update"] = datetime.now().isoformat()
            logger.info(f"All users ready in party {party_id}")
            await sio.emit("all_ready", {
                "time": playback_state.get("time", 0),
                "playing": playback_state.get("playing", False),
            }, room=party_id)
        else:
            ready_names = [party["users"].get(s, "?") for s in rc["ready_sids"]]
            waiting_names = [party["users"].get(s, "?") for s in rc["expected_sids"] - rc["ready_sids"]]
            await sio.emit("ready_check_update", {
                "ready": ready_names, "waiting": waiting_names,
            }, room=party_id)

    async def _restart_video_from_beginning(party, party_id, selector_client_id,
                                              item_id, item_name, item_overview):
        """Fetch fresh media info, stop existing streams, create per-user
        streams starting at 0, broadcast video_selected + ready_check.

        `selector_client_id` is stored as `current_video.selected_by` so
        the selector survives reloads / sid changes.

        Returns True on success, False on failure (caller should emit error).
        """
        access_token, user_id = _host_creds(party)
        playback_info = emby_client.get_playback_info(
            item_id, access_token=access_token, user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            return False

        media_source = playback_info["MediaSources"][0]
        default_audio = _default_audio_index(media_source)
        run_time_ticks = media_source.get("RunTimeTicks", 0)
        run_time_seconds = run_time_ticks / 10_000_000 if run_time_ticks else None

        # Stop all previous user streams
        prev_time = party["playback_state"].get("time", 0)
        _stop_all_user_streams(party, prev_time)

        # Store shared video info (no per-user fields). selected_by is the
        # persistent client_id, not the current sid.
        party["current_video"] = {
            "item_id": item_id, "title": item_name, "overview": item_overview,
            "run_time_seconds": run_time_seconds,
            "selected_by": selector_client_id,
        }

        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }

        # Start a ready check so clients show the waiting overlay until
        # every user has loaded their stream
        _start_ready_check(party, party_id)
        waiting_names = [party["users"].get(s, "?") for s in party["ready_check"]["expected_sids"]]

        # Create per-user streams and emit individually
        for user_sid in list(party["users"].keys()):
            stream = _create_user_stream(
                party, party_id, user_sid, item_id, media_source,
                audio_index=default_audio, subtitle_index=None,
                quality=DEFAULT_QUALITY, start_seconds=0,
            )
            if not stream:
                continue

            stream_url = stream["stream_url_base"]
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = token_manager.get_or_create(party_id, user_sid)
                if user_token:
                    stream_url += f"&token={user_token}"

            await sio.emit("video_selected", {
                "video": {
                    "item_id": item_id, "title": item_name, "overview": item_overview,
                    "stream_url": stream_url,
                    "audio_index": default_audio, "subtitle_index": None,
                    "media_source_id": stream["media_source_id"],
                    "selected_by": selector_client_id, "quality": DEFAULT_QUALITY,
                }
            }, to=user_sid)

        # Tell everyone the ready check is in progress
        await sio.emit("ready_check_update", {
            "ready": [], "waiting": waiting_names,
        }, room=party_id)

        return True

    # Expose the restart helper so party.py can reuse it for vote-pass restarts
    ctx['restart_video_from_beginning'] = _restart_video_from_beginning
    ctx['create_user_stream'] = _create_user_stream

    @sio.on("select_video")
    async def handle_select_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        item_id = data.get("item_id")
        item_name = data.get("item_name", "Unknown")
        item_overview = data.get("item_overview", "")

        if not party_manager.exists(party_id):
            await sio.emit("error", {"message": "Watch party not found"}, to=sid)
            return

        party = party_manager.get(party_id)

        # Party must be UNLOCKED. PLAYING-ONLY does not allow new picks
        # because the host is gone and a new transcode can not be started.
        if not party_manager.is_unlocked(party_id):
            await sio.emit(
                "error",
                {"message": "Party has no host -- login to become host first"},
                to=sid,
            )
            return

        selector_client_id = _client_id_for_sid(party, sid)
        if not selector_client_id:
            await sio.emit("error", {"message": "Not a party member"}, to=sid)
            return

        success = await _restart_video_from_beginning(
            party, party_id, selector_client_id, item_id, item_name, item_overview
        )
        if not success:
            await sio.emit("error", {"message": "Failed to load video"}, to=sid)
            return

    @sio.on("stop_video")
    async def handle_stop_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)

        if not party or not party.get("current_video"):
            return

        caller_client_id = _client_id_for_sid(party, sid)
        if party["current_video"].get("selected_by") != caller_client_id:
            await sio.emit("error", {"message": "Only the selector can stop the video"}, to=sid)
            return

        video_title = party["current_video"].get("title", "Unknown")
        username = party["users"].get(sid, "Unknown")
        current_time = party["playback_state"].get("time", 0)

        _stop_all_user_streams(party, current_time)

        party["current_video"] = None
        party["ready_check"] = None
        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }

        # PLAYING-ONLY -> LOCKED transition if the host was gone.
        _wipe_host_if_orphan(party_id, party)

        await sio.emit("video_stopped", {
            "message": f"{username} stopped the video", "stopped_by": username,
        }, room=party_id)
        logger.info(f"User {username} stopped '{video_title}' in party {party_id}")

    @sio.on("change_streams")
    async def handle_change_streams(sid, data):
        """Per-user stream change (audio/subtitle/quality).

        Silent swap of the requesting user's stream. Other users keep
        playing normally; no party-wide pause, no ready check.
        """
        party_id = data.get("party_id", "").strip().upper()
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")
        quality = data.get("quality")

        party = party_manager.get(party_id)
        if not party or not party.get("current_video"):
            return

        # Need a usable host token. Allowed in both UNLOCKED and
        # PLAYING-ONLY because the in-flight video already has a session
        # under the stored token -- we just need it for the new transcode.
        if not party_manager.has_host_token(party_id):
            await sio.emit(
                "error",
                {"message": "Party token has expired"},
                to=sid,
            )
            return

        current_video = party["current_video"]
        item_id = current_video["item_id"]
        access_token, user_id = _host_creds(party)

        if not quality or quality not in QUALITY_PRESETS:
            old_stream = party.get("user_streams", {}).get(sid, {})
            quality = old_stream.get("quality", DEFAULT_QUALITY)

        # Snapshot the party clock using the same elapsed-time projection
        # the sync handlers use.
        ps = party["playback_state"]
        was_playing = ps.get("playing", False)
        snapshot_time = ps.get("time", 0)
        if was_playing and ps.get("last_update"):
            try:
                last_update = datetime.fromisoformat(ps["last_update"])
                elapsed = (datetime.now() - last_update).total_seconds()
                if 0 < elapsed < 30:
                    snapshot_time += elapsed
            except Exception:
                pass

        # Stop this user's old transcode. Party clock keeps running.
        _stop_user_stream(party, sid, snapshot_time)

        preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])
        playback_info = emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            max_streaming_bitrate=preset["bitrate"],
            start_time_ticks=int(snapshot_time * 10_000_000) if snapshot_time > 0 else 0,
            access_token=access_token,
            user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            return

        media_source = playback_info["MediaSources"][0]

        # Recompute the current party time after the Emby round-trip.
        current_time = ps.get("time", 0)
        if was_playing and ps.get("last_update"):
            try:
                last_update = datetime.fromisoformat(ps["last_update"])
                elapsed = (datetime.now() - last_update).total_seconds()
                if 0 < elapsed < 30:
                    current_time += elapsed
            except Exception:
                pass

        stream = _create_user_stream(
            party, party_id, sid, item_id, media_source,
            audio_index=audio_index, subtitle_index=subtitle_index,
            quality=quality, start_seconds=current_time,
        )
        if not stream:
            return

        stream_url = stream["stream_url_base"]
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = token_manager.get_or_create(party_id, sid)
            if user_token:
                stream_url += f"&token={user_token}"

        await sio.emit("streams_changed", {
            "video": {
                "item_id": item_id, "title": current_video["title"],
                "overview": current_video["overview"], "stream_url": stream_url,
                "audio_index": audio_index, "subtitle_index": subtitle_index,
                "media_source_id": stream["media_source_id"],
                "selected_by": current_video.get("selected_by"), "quality": quality,
            },
            "current_time": current_time,
            "was_playing": was_playing,
        }, to=sid)

        username = party["users"].get(sid, "Unknown")
        logger.info(
            f"Stream changed for {username}: audio={audio_index}, "
            f"sub={subtitle_index}, quality={quality}, resume_at={current_time:.1f}s"
        )

    @sio.on("video_ended")
    async def handle_video_ended(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        logger.info(f"Video ended in party {party_id}")
        final_pos = party.get("current_video", {}).get("run_time_seconds", 0)
        _stop_all_user_streams(party, final_pos)

        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }
        party["ready_check"] = None

        # If host already left, this is the moment we fully lock the party.
        _wipe_host_if_orphan(party_id, party)

        await sio.emit("video_ended", {
            "party_id": party_id, "timestamp": datetime.now().isoformat(),
        }, room=party_id)

    @sio.on("report_progress")
    async def handle_report_progress(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party or not party.get("current_video"):
            return

        user_stream = party.get("user_streams", {}).get(sid)
        if not user_stream or not user_stream.get("play_session_id"):
            return

        # Only the selector updates the authoritative party clock.
        # Match by persistent client_id so a reload preserves the role.
        current_video = party["current_video"]
        caller_client_id = _client_id_for_sid(party, sid)
        if current_video.get("selected_by") == caller_client_id:
            party["playback_state"]["time"] = current_time
            party["playback_state"]["last_update"] = datetime.now().isoformat()

        is_playing = party["playback_state"].get("playing", False)
        access_token, user_id = _host_creds(party)
        emby_client.report_playback_progress(
            item_id=current_video["item_id"],
            media_source_id=user_stream["media_source_id"],
            play_session_id=user_stream["play_session_id"],
            position_seconds=current_time, is_paused=not is_playing, event_name="TimeUpdate",
            audio_index=user_stream.get("audio_index"),
            subtitle_index=user_stream.get("subtitle_index") if user_stream.get("subtitle_index") != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds"),
            access_token=access_token,
            user_id=user_id,
        )

    @sio.on("stream_ready")
    async def handle_stream_ready(sid, data):
        """Client signals their HLS stream is loaded and ready to play."""
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        user_stream = party.get("user_streams", {}).get(sid)
        if user_stream:
            user_stream["ready"] = True

        rc = party.get("ready_check")
        if rc and rc.get("active"):
            rc["ready_sids"].add(sid)
            username = party["users"].get(sid, "Unknown")
            logger.debug(f"{username} stream ready in party {party_id}")
            await _check_all_ready(party, party_id)
