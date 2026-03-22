"""Party handlers: join_party, leave_party"""

from datetime import datetime
from backend.src.utils import generate_random_username
from backend.src.stream_builder import DEFAULT_QUALITY


def register(ctx):
    sio = ctx['sio']
    config = ctx['config']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    token_manager = ctx['token_manager']

    @sio.on("join_party")
    async def handle_join_party(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        username = data.get("username", "").strip()

        if not username:
            username = generate_random_username()
            logger.info(f"Generated random username: {username}")

        if not party_manager.exists(party_id):
            logger.warning(f"Join failed: party {party_id} not found (user: {username})")
            await sio.emit("error", {"message": "Watch party not found"}, to=sid)
            return

        party = party_manager.get(party_id)

        # Evict stale SID if same username is already in party
        for old_sid, existing_name in list(party["users"].items()):
            if existing_name == username and old_sid != sid:
                del party["users"][old_sid]
                await sio.leave_room(old_sid, party_id)
                logger.info(f"Evicted stale session {old_sid} for {username}")
                if party["current_video"] and party["current_video"].get("selected_by") == old_sid:
                    party["current_video"]["selected_by"] = sid
                break

        # Check max users
        if config.MAX_USERS_PER_PARTY > 0 and len(party["users"]) >= config.MAX_USERS_PER_PARTY:
            logger.warning(f"Party {party_id} is full")
            await sio.emit("error", {"message": f"Party is full (max {config.MAX_USERS_PER_PARTY} users)"}, to=sid)
            return

        await sio.enter_room(sid, party_id)
        party["users"][sid] = username

        await sio.emit("user_joined", {
            "username": username,
            "users": list(party["users"].values()),
        }, room=party_id)

        # Build sync state for new joiner
        current_video = None
        if party["current_video"]:
            current_video = {
                "item_id": party["current_video"]["item_id"],
                "title": party["current_video"]["title"],
                "overview": party["current_video"]["overview"],
                "audio_index": party["current_video"]["audio_index"],
                "subtitle_index": party["current_video"]["subtitle_index"],
                "media_source_id": party["current_video"].get("media_source_id"),
                "selected_by": party["current_video"].get("selected_by"),
                "quality": party["current_video"].get("quality", DEFAULT_QUALITY),
            }

            stream_url = party["current_video"]["stream_url_base"]
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = token_manager.get_or_create(party_id, sid)
                if user_token:
                    stream_url += f"&token={user_token}"
            current_video["stream_url"] = stream_url

        # Calculate accurate time for new joiner
        playback_state = party["playback_state"].copy()
        if playback_state.get("playing") and playback_state.get("last_update"):
            try:
                last_update = datetime.fromisoformat(playback_state["last_update"])
                elapsed = (datetime.now() - last_update).total_seconds()
                playback_state["time"] = playback_state["time"] + elapsed
            except Exception as e:
                logger.warning(f"Error calculating playback time: {e}")

        await sio.emit("sync_state", {
            "current_video": current_video,
            "playback_state": playback_state,
        }, to=sid)

    @sio.on("leave_party")
    async def handle_leave_party(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)

        if party and sid in party["users"]:
            username = party["users"][sid]
            sio.leave_room(sid, party_id)
            del party["users"][sid]
            await sio.emit("user_left", {
                "username": username,
                "users": list(party["users"].values()),
            }, room=party_id)
