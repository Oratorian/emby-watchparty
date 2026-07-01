"""Chat handlers: chat_message, toggle_library"""

import time as _time
from collections import deque
from datetime import datetime


# Chat spam guardrails. Previously any joined member could emit
# arbitrary-size messages at any rate, and the handler fanned them out
# to every party member with no coercion, length check, or throttle --
# a room-wide amplification / event-loop DoS primitive. Values below
# match typical chat-service limits: 2 KiB per message and 5 msgs / 3s
# per sid (bursts of 5 allowed, sustained rate capped).
_CHAT_MAX_LEN = 2048
_CHAT_BURST = 5
_CHAT_WINDOW_SECS = 3.0
_CHAT_HISTORY: dict[str, deque[float]] = {}


def _chat_throttled(sid: str) -> bool:
    """Sliding-window rate check. True iff sid should be dropped."""
    now = _time.monotonic()
    cutoff = now - _CHAT_WINDOW_SECS
    bucket = _CHAT_HISTORY.setdefault(sid, deque(maxlen=_CHAT_BURST + 1))
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _CHAT_BURST:
        return True
    bucket.append(now)
    return False


def register(ctx):
    sio = ctx['sio']
    logger = ctx['logger']
    party_manager = ctx['party_manager']

    @sio.on("chat_message")
    async def handle_chat_message(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        raw_message = data.get("message", "")
        # Coerce to str so a nested list/dict payload of equal byte
        # count doesn't sneak past the length cap. Truncate to the
        # ceiling; better than dropping the entire message on any
        # accidental paste.
        message = str(raw_message)[:_CHAT_MAX_LEN] if raw_message else ""
        if not message.strip():
            return
        party = party_manager.get(party_id)

        if party and sid in party["users"]:
            if _chat_throttled(sid):
                logger.debug(f"Chat message dropped: sid={sid} rate-limited in {party_id}")
                return
            username = party["users"][sid]
            # Look up the sender's persistent avatar identity so the
            # client can render their chosen avatar instead of the
            # username-derived monsterid.
            client_id = party.get("sid_client_ids", {}).get(sid)
            participant = party.get("participants", {}).get(client_id) if client_id else None
            avatar_uuid = participant.get("avatar_uuid") if participant else None
            await sio.emit("chat_message", {
                "username": username,
                "avatar_uuid": avatar_uuid,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }, room=party_id)

    @sio.on("toggle_library")
    async def handle_toggle_library(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        show = data.get("show", False)

        # Only the host can toggle the library visibility globally --
        # a non-host emitting this used to flip the panel for the whole
        # room (griefing potential during a movie night).
        party = party_manager.get(party_id)
        if not party:
            return
        caller_client_id = party.get("sid_client_ids", {}).get(sid)
        if caller_client_id != party.get("host_client_id"):
            logger.debug(
                f"toggle_library REJECTED: sid={sid} is not host of {party_id}"
            )
            return

        logger.info(f"Library toggled in party {party_id}: show={show}")
        await sio.emit("toggle_library", {"show": show}, room=party_id)
