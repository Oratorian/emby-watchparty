"""
Party Management Handlers
Events: join_party, leave_party
"""

from flask_socketio import emit, join_room, leave_room
from flask import request
from datetime import datetime

from src.socket_handlers.quality import DEFAULT_QUALITY


def register(deps):
    socketio = deps['socketio']
    config = deps['config']
    logger = deps['logger']
    watch_parties = deps['watch_parties']
    hls_tokens = deps['hls_tokens']
    generate_random_username = deps['generate_random_username']
    get_user_token = deps['get_user_token']

    @socketio.on("join_party")
    def handle_join_party(data):
        """User joins a watch party"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching
        username = data.get("username", "").strip()

        # Generate random username if empty
        if not username:
            username = generate_random_username()
            logger.info(f"Generated random username: {username}")

        if party_id not in watch_parties:
            logger.warning(f"Join failed: party {party_id} not found (user: {username})")
            emit("error", {"message": "Watch party not found"})
            return

        # Evict stale SID if same username is already in the party (e.g. page refresh)
        old_sid = None
        for sid, existing_username in list(watch_parties[party_id]["users"].items()):
            if existing_username == username and sid != request.sid:
                old_sid = sid
                del watch_parties[party_id]["users"][sid]
                leave_room(party_id, sid=sid)
                logger.info(
                    f"Evicted stale session {sid} for user {username} in party {party_id}"
                )
                # Transfer video control so refreshed user can still stop/report progress
                if (
                    watch_parties[party_id]["current_video"]
                    and watch_parties[party_id]["current_video"].get("selected_by") == sid
                ):
                    watch_parties[party_id]["current_video"]["selected_by"] = request.sid
                break

        # Check max users per party limit (skip if this is a rejoin)
        if config.MAX_USERS_PER_PARTY > 0 and old_sid is None:
            current_user_count = len(watch_parties[party_id]["users"])
            if current_user_count >= config.MAX_USERS_PER_PARTY:
                logger.warning(
                    f"Party {party_id} is full ({current_user_count}/{config.MAX_USERS_PER_PARTY})"
                )
                emit(
                    "error",
                    {
                        "message": f"Party is full (max {config.MAX_USERS_PER_PARTY} users)"
                    },
                )
                return

        # Join the room
        join_room(party_id)

        # Add user to party
        watch_parties[party_id]["users"][request.sid] = username

        # Notify everyone
        emit(
            "user_joined",
            {
                "username": username,
                "users": list(watch_parties[party_id]["users"].values()),
            },
            room=party_id,
        )

        # Send current state to the new user with their individual token
        party = watch_parties[party_id]
        current_video = None

        if party["current_video"]:
            # Build video object with individual token for this user
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

            # Add stream URL with individual token
            stream_url = party["current_video"]["stream_url_base"]
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = get_user_token(
                    party_id, request.sid, hls_tokens, config, logger
                )
                if user_token:
                    stream_url += f"&token={user_token}"
                    logger.debug(
                        f"New user {username} joining party {party_id} with token: {user_token[:16]}..."
                    )
                else:
                    logger.warning(
                        f"Failed to generate token for new user {username} in party {party_id}"
                    )

            current_video["stream_url"] = stream_url

        # Calculate accurate current time for new joiner
        playback_state = party["playback_state"].copy()
        if playback_state.get("playing") and playback_state.get("last_update"):
            try:
                # Calculate elapsed time since last update
                last_update = datetime.fromisoformat(playback_state["last_update"])
                elapsed_seconds = (datetime.now() - last_update).total_seconds()

                # Add elapsed time to stored time for accurate sync
                stored_time = playback_state["time"]
                current_time = stored_time + elapsed_seconds
                playback_state["time"] = current_time

                logger.debug(
                    f"New joiner sync: stored_time={stored_time:.2f}s, elapsed={elapsed_seconds:.2f}s, current_time={current_time:.2f}s"
                )
            except Exception as e:
                logger.warning(f"Error calculating playback time for new joiner: {e}")

        emit(
            "sync_state",
            {"current_video": current_video, "playback_state": playback_state},
        )

    @socketio.on("leave_party")
    def handle_leave_party(data):
        """User leaves a watch party"""
        party_id = (
            data.get("party_id", "").strip().upper()
        )  # Convert to uppercase for case-insensitive matching

        if (
            party_id in watch_parties
            and request.sid in watch_parties[party_id]["users"]
        ):
            username = watch_parties[party_id]["users"][request.sid]
            leave_room(party_id)
            del watch_parties[party_id]["users"][request.sid]

            emit(
                "user_left",
                {
                    "username": username,
                    "users": list(watch_parties[party_id]["users"].values()),
                },
                room=party_id,
            )
