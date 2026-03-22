"""Chat handlers: chat_message, toggle_library"""

from datetime import datetime


def register(ctx):
    sio = ctx['sio']
    logger = ctx['logger']
    party_manager = ctx['party_manager']

    @sio.on("chat_message")
    async def handle_chat_message(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        message = data.get("message", "")
        party = party_manager.get(party_id)

        if party and sid in party["users"]:
            username = party["users"][sid]
            await sio.emit("chat_message", {
                "username": username,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }, room=party_id)

    @sio.on("toggle_library")
    async def handle_toggle_library(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        show = data.get("show", False)

        if party_manager.exists(party_id):
            logger.info(f"Library toggled in party {party_id}: show={show}")
            await sio.emit("toggle_library", {"show": show}, room=party_id)
