"""Connection handlers: connect, disconnect"""

from datetime import datetime


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    logger = ctx['logger']
    party_manager = ctx['party_manager']

    @sio.event
    async def connect(sid, environ):
        logger.info(f"Client connected: {sid}")
        await sio.emit("connected", {"sid": sid}, to=sid)

    @sio.event
    async def disconnect(sid):
        logger.info(f"Client disconnected: {sid}")
        handle_disconnect_from_vote = ctx.get('handle_disconnect_from_vote')

        for party_id, party in list(party_manager.get_all().items()):
            # Handle late-joiner vote cleanup (the disconnecting user may be
            # the pending late joiner, or an eligible voter whose absence
            # changes the majority math).
            if party.get("pending_join") and handle_disconnect_from_vote:
                pj = party["pending_join"]
                if pj["sid"] == sid or sid in pj.get("eligible_voters", set()):
                    await handle_disconnect_from_vote(party, party_id, sid)

            if sid in party["users"]:
                username = party["users"][sid]

                # Stop this user's individual transcode
                user_stream = party.get("user_streams", {}).get(sid)
                if user_stream and user_stream.get("play_session_id") and party.get("current_video"):
                    current_time = party["playback_state"].get("time", 0)
                    emby_client.report_playback_stopped(
                        item_id=party["current_video"]["item_id"],
                        media_source_id=user_stream["media_source_id"],
                        play_session_id=user_stream["play_session_id"],
                        position_seconds=current_time,
                        run_time_seconds=party["current_video"].get("run_time_seconds"),
                    )
                    emby_client.stop_active_encodings(play_session_id=user_stream["play_session_id"])
                party.get("user_streams", {}).pop(sid, None)

                del party["users"][sid]
                party.setdefault("sid_client_ids", {}).pop(sid, None)
                if "drift_strikes" in party and sid in party["drift_strikes"]:
                    del party["drift_strikes"][sid]

                # Remove from any active ready check so we don't wait forever
                # for a signal from a disconnected client
                rc = party.get("ready_check")
                if rc and rc.get("active"):
                    rc["expected_sids"].discard(sid)
                    rc["ready_sids"].discard(sid)
                    if rc["ready_sids"] >= rc["expected_sids"] and rc["expected_sids"]:
                        party["ready_check"] = None
                        playback_state = party.get("playback_state", {})
                        if playback_state.get("playing"):
                            playback_state["last_update"] = datetime.now().isoformat()
                        logger.info(f"All users ready in party {party_id} (after disconnect)")
                        await sio.emit("all_ready", {
                            "time": playback_state.get("time", 0),
                            "playing": playback_state.get("playing", False),
                        }, room=party_id)
                    elif not rc["expected_sids"]:
                        # No one left to wait for -- cancel the check entirely
                        party["ready_check"] = None
                    else:
                        ready_names = [party["users"].get(s, "?") for s in rc["ready_sids"]]
                        waiting_names = [party["users"].get(s, "?") for s in rc["expected_sids"] - rc["ready_sids"]]
                        await sio.emit("ready_check_update", {
                            "ready": ready_names, "waiting": waiting_names,
                        }, room=party_id)

                await sio.emit(
                    "user_left",
                    {"username": username, "users": list(party["users"].values())},
                    room=party_id,
                    skip_sid=sid,
                )
