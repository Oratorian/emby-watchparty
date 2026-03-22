"""Connection handlers: connect, disconnect"""


def register(ctx):
    sio = ctx['sio']
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
                del party["users"][sid]
                if "drift_strikes" in party and sid in party["drift_strikes"]:
                    del party["drift_strikes"][sid]
                await sio.emit(
                    "user_left",
                    {"username": username, "users": list(party["users"].values())},
                    room=party_id,
                    skip_sid=sid,
                )
