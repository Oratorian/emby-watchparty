"""Connection handlers: connect, disconnect"""


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
        for party_id, party in party_manager.get_all().items():
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
                if "drift_strikes" in party and sid in party["drift_strikes"]:
                    del party["drift_strikes"][sid]
                await sio.emit(
                    "user_left",
                    {"username": username, "users": list(party["users"].values())},
                    room=party_id,
                    skip_sid=sid,
                )
