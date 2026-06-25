"""Sync handlers: play, pause, seek"""

from datetime import datetime


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    logger = ctx['logger']
    party_manager = ctx['party_manager']

    def _get_server_time(party):
        """Get the server's best estimate of current playback position."""
        ps = party["playback_state"]
        server_time = ps.get("time", 0)
        if ps.get("playing") and ps.get("last_update"):
            try:
                last = datetime.fromisoformat(ps["last_update"])
                elapsed = (datetime.now() - last).total_seconds()
                if 0 < elapsed < 30:
                    server_time += elapsed
            except Exception:
                pass
        return server_time

    def _client_id_for_sid(party, sid):
        return party.get("sid_client_ids", {}).get(sid)

    def _report_emby_progress(party, sid, position, is_paused, event_name):
        """Report playback progress to Emby for a specific user's stream."""
        current_video = party.get("current_video")
        user_stream = party.get("user_streams", {}).get(sid)
        if not current_video or not user_stream or not user_stream.get("play_session_id"):
            return
        emby_client.report_playback_progress(
            item_id=current_video["item_id"],
            media_source_id=user_stream["media_source_id"],
            play_session_id=user_stream["play_session_id"],
            position_seconds=position, is_paused=is_paused, event_name=event_name,
            audio_index=user_stream.get("audio_index"),
            subtitle_index=user_stream.get("subtitle_index") if user_stream.get("subtitle_index") != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds"),
            access_token=party.get("host_access_token"),
            user_id=party.get("host_user_id"),
        )

    @sio.on("play")
    async def handle_play(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party:
            return

        current_video = party.get("current_video")
        caller_client_id = _client_id_for_sid(party, sid)
        is_selector = current_video and current_video.get("selected_by") == caller_client_id

        # Everyone can toggle play, but only the selector's time is trusted
        if not is_selector:
            current_time = _get_server_time(party)

        party["playback_state"] = {
            "playing": True, "time": current_time,
            "last_update": datetime.now().isoformat(),
        }

        # Report to Emby for the user who triggered play
        _report_emby_progress(party, sid, current_time, is_paused=False, event_name="Unpause")

        username = party["users"].get(sid, "Someone")
        # Broadcast to everyone including the sender. The client-side
        # handler is idempotent on the sender's own video (already
        # playing means ve.play() is a no-op, and the position-delta
        # guard skips re-seeks within 0.3s), and centralising the chat
        # message on this one broadcast prevents the local-fire +
        # broadcast-fire duplicate that used to show up whenever the
        # server broadcasted to the sender (e.g. seek during playback).
        # See the matching comment in handle_seek.
        await sio.emit("play", {"time": current_time, "username": username},
                        room=party_id)

    @sio.on("pause")
    async def handle_pause(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party:
            return

        current_video = party.get("current_video")
        caller_client_id = _client_id_for_sid(party, sid)
        is_selector = current_video and current_video.get("selected_by") == caller_client_id

        if not is_selector:
            current_time = _get_server_time(party)

        party["playback_state"] = {
            "playing": False, "time": current_time,
            "last_update": datetime.now().isoformat(),
        }

        _report_emby_progress(party, sid, current_time, is_paused=True, event_name="Pause")

        username = party["users"].get(sid, "Someone")
        # Broadcast to everyone including the sender. See the matching
        # comment on handle_play / handle_seek for the rationale.
        await sio.emit("pause", {"time": current_time, "username": username},
                        room=party_id)

    @sio.on("seek")
    async def handle_seek(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        seek_time = data.get("time", 0)
        was_playing = data.get("was_playing", False)
        party = party_manager.get(party_id)
        if not party:
            return

        # Ignore seek events while a ready check is active. During a
        # ready check, clients are still buffering their streams and
        # may emit stray native `seeked` events (from HLS.js initial
        # frame decoding or currentTime=0 resets). Treating those as
        # real user seeks creates cascades of 00:00 seek spam across
        # the party. Real user-initiated seeks only happen after the
        # ready-check overlay dismisses.
        rc = party.get("ready_check")
        if rc and rc.get("active"):
            logger.debug(f"Ignoring seek from {sid}: ready check active in {party_id}")
            return

        party["playback_state"]["playing"] = was_playing
        party["playback_state"]["time"] = seek_time
        party["playback_state"]["last_update"] = datetime.now().isoformat()

        _report_emby_progress(party, sid, seek_time, is_paused=not was_playing, event_name="TimeUpdate")

        username = party["users"].get(sid, "Someone")

        if was_playing:
            logger.info("Seek during playback - pausing all clients first for buffering")

            # Start a ready check so everyone buffers before resuming
            expected = set(party["users"].keys())
            party["ready_check"] = {
                "active": True,
                "expected_sids": expected,
                "ready_sids": set(),
            }

            waiting_names = [party["users"].get(s, "?") for s in expected]

            # Pause everyone, show overlay, then seek
            await sio.emit("force_pause_before_seek", {"time": seek_time},
                            room=party_id)
            await sio.emit("ready_check_update", {
                "ready": [], "waiting": waiting_names,
            }, room=party_id)
            await sio.emit("seek", {
                "time": seek_time, "playing": True, "username": username,
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
                "time": seek_time, "playing": False, "username": username,
            }, room=party_id)
