"""Sync handlers: play, pause, seek."""


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    logger = ctx['logger']
    party_manager = ctx['party_manager']

    async def _report_emby_progress(snapshot, position, is_paused, event_name):
        """Report playback progress to Emby for a specific user's stream."""
        current_video = snapshot.current_video
        user_stream = snapshot.user_stream
        if not current_video or not user_stream or not user_stream.play_session_id:
            return
        await emby_client.report_playback_progress(
            item_id=current_video["item_id"],
            media_source_id=user_stream.media_source_id,
            play_session_id=user_stream.play_session_id,
            position_seconds=position, is_paused=is_paused, event_name=event_name,
            audio_index=user_stream.audio_index,
            subtitle_index=user_stream.subtitle_index if user_stream.subtitle_index != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds"),
            access_token=snapshot.host_access_token,
            user_id=snapshot.host_user_id,
        )

    @sio.on("play")
    async def handle_play(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        commit = await party_manager.commit_playback_control(
            party_id, sid, playing=True, position=current_time
        )
        if commit is None:
            logger.info(
                f"handle_play REJECTED: sid={sid} is not a member of {party_id}"
            )
            return
        logger.debug(
            f"PLAY accepted from {commit.username} (sid={sid}, "
            f"client={commit.client_id}) "
            f"in {party_id} at {current_time:.1f}s -> broadcasting to room"
        )

        # Broadcast to everyone including the sender. The client-side
        # handler is idempotent on the sender's own video (already
        # playing means ve.play() is a no-op, and the position-delta
        # guard skips re-seeks within 0.3s), and centralising the chat
        # message on this one broadcast prevents the local-fire +
        # broadcast-fire duplicate that used to show up whenever the
        # server broadcasted to the sender (e.g. seek during playback).
        # See the matching comment in handle_seek.
        await sio.emit("play", {"time": current_time, "username": commit.username},
                        room=party_id)
        await _report_emby_progress(
            commit.report, current_time, is_paused=False, event_name="Unpause"
        )

    @sio.on("pause")
    async def handle_pause(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        commit = await party_manager.commit_playback_control(
            party_id, sid, playing=False, position=current_time
        )
        if commit is None:
            logger.info(
                f"handle_pause REJECTED: sid={sid} is not a member of {party_id}"
            )
            return
        logger.debug(
            f"PAUSE accepted from {commit.username} (sid={sid}, "
            f"client={commit.client_id}) "
            f"in {party_id} at {current_time:.1f}s -> broadcasting to room"
        )

        # Broadcast to everyone including the sender. See the matching
        # comment on handle_play / handle_seek for the rationale.
        await sio.emit("pause", {"time": current_time, "username": commit.username},
                        room=party_id)
        await _report_emby_progress(
            commit.report, current_time, is_paused=True, event_name="Pause"
        )

    @sio.on("seek")
    async def handle_seek(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        seek_time = data.get("time", 0)
        was_playing = data.get("was_playing", False)
        commit = await party_manager.commit_seek(
            party_id, sid, position=seek_time, was_playing=was_playing
        )
        if commit is None:
            logger.debug(f"Ignoring unauthorized or overlapping seek in {party_id}")
            return

        if was_playing:
            logger.info("Seek during playback - pausing all clients first for buffering")

            # Start a ready check so everyone buffers before resuming
            # Pause everyone, show overlay, then seek
            await sio.emit("force_pause_before_seek", {"time": seek_time},
                            room=party_id)
            await sio.emit("ready_check_update", {
                "ready": [], "waiting": list(commit.waiting_names),
            }, room=party_id)
            await sio.emit("seek", {
                "time": seek_time, "playing": True, "username": commit.username,
                "wait_for_ready": True,
            }, room=party_id)
        else:
            # Broadcast to everyone including the seeker. The client-side
            # handler is idempotent on the seeker's own video (it only
            # re-seeks when its currentTime differs from the broadcast
            # by >0.3s, and calling pause() on an already-paused video
            # is a no-op), and centralising the chat message on this
            # one broadcast means the seeker doesn't have to fire a
            # second addSystemMessage locally just to see their own
            # "X seeked to ..." line. Without this, scrubber seeks
            # during playback (which already broadcast to everyone for
            # the ready-check handshake) produced a duplicate "seeked
            # to" message in chat.
            await sio.emit("seek", {
                "time": seek_time, "playing": False, "username": commit.username,
            }, room=party_id)

        await _report_emby_progress(
            commit.report, seek_time,
            is_paused=not was_playing,
            event_name="TimeUpdate",
        )
