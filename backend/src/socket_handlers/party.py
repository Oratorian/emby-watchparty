"""Party handlers: join_party, leave_party"""

from datetime import datetime
from backend.src.utils import generate_random_username
from backend.src.stream_builder import DEFAULT_QUALITY


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
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
                # Transfer stream ownership
                old_stream = party.get("user_streams", {}).pop(old_sid, None)
                if old_stream:
                    party["user_streams"][sid] = old_stream
                break

        # Check max users
        if config.MAX_USERS_PER_PARTY > 0 and len(party["users"]) >= config.MAX_USERS_PER_PARTY:
            logger.warning(f"Party {party_id} is full")
            await sio.emit("error", {"message": f"Party is full (max {config.MAX_USERS_PER_PARTY} users)"}, to=sid)
            return

        await sio.enter_room(sid, party_id)
        party["users"][sid] = username
        party.setdefault("join_times", {})[sid] = datetime.now().isoformat()

        await sio.emit("user_joined", {
            "username": username,
            "users": list(party["users"].values()),
        }, room=party_id)

        # Build sync state for new joiner
        current_video = None
        stream_url = None

        if party["current_video"]:
            cv = party["current_video"]
            current_video = {
                "item_id": cv["item_id"],
                "title": cv["title"],
                "overview": cv["overview"],
                "selected_by": cv.get("selected_by"),
            }

            # Create a per-user stream for the late joiner at the current position
            current_time = party["playback_state"].get("time", 0)
            if party["playback_state"].get("playing") and party["playback_state"].get("last_update"):
                try:
                    last_update = datetime.fromisoformat(party["playback_state"]["last_update"])
                    elapsed = (datetime.now() - last_update).total_seconds()
                    current_time += elapsed
                except Exception as e:
                    logger.warning(f"Error calculating playback time: {e}")

            playback_info = emby_client.get_playback_info(cv["item_id"])
            if playback_info and "MediaSources" in playback_info:
                media_source = playback_info["MediaSources"][0]
                media_source_id = media_source["Id"]
                play_session_id = playback_info.get("PlaySessionId")

                start_ticks = int(current_time * 10_000_000) if current_time > 0 else None

                from backend.src.stream_builder import StreamBuilder
                builder = StreamBuilder(emby_client, logger)

                # Use defaults for late joiner (they can change later)
                default_audio = None
                if "MediaStreams" in media_source:
                    for s in media_source["MediaStreams"]:
                        if s.get("Type") == "Audio" and s.get("IsDefault"):
                            default_audio = s.get("Index")
                            break
                    if default_audio is None:
                        for s in media_source["MediaStreams"]:
                            if s.get("Type") == "Audio":
                                default_audio = s.get("Index")
                                break

                stream_url_base = builder.build_stream_url(
                    item_id=cv["item_id"],
                    app_prefix=config.APP_PREFIX,
                    media_source=media_source,
                    media_source_id=media_source_id,
                    play_session_id=play_session_id,
                    audio_index=default_audio,
                    subtitle_index=None,
                    quality=DEFAULT_QUALITY,
                    start_time_ticks=start_ticks,
                )

                party.setdefault("user_streams", {})[sid] = {
                    "play_session_id": play_session_id,
                    "media_source_id": media_source_id,
                    "stream_url_base": stream_url_base,
                    "audio_index": default_audio,
                    "subtitle_index": None,
                    "quality": DEFAULT_QUALITY,
                    "ready": False,
                }

                emby_client.report_playback_start(
                    item_id=cv["item_id"], media_source_id=media_source_id,
                    play_session_id=play_session_id, position_seconds=current_time,
                    audio_index=default_audio,
                    run_time_seconds=cv.get("run_time_seconds"),
                )

                stream_url = stream_url_base
                if config.ENABLE_HLS_TOKEN_VALIDATION:
                    user_token = token_manager.get_or_create(party_id, sid)
                    if user_token:
                        stream_url += f"&token={user_token}"

                current_video["stream_url"] = stream_url
                current_video["audio_index"] = default_audio
                current_video["subtitle_index"] = None
                current_video["quality"] = DEFAULT_QUALITY

                logger.info(f"Late joiner {username}: stream at {current_time:.1f}s")

        # Calculate accurate time for sync_state
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

            await sio.leave_room(sid, party_id)
            del party["users"][sid]
            await sio.emit("user_left", {
                "username": username,
                "users": list(party["users"].values()),
            }, room=party_id)
