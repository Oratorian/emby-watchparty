"""Chat handlers: chat_message, toggle_library"""

from datetime import UTC, datetime

from backend.src.rate_limit import parse_rate

# Chat spam guardrails. Previously any joined member could emit
# arbitrary-size messages at any rate, and the handler fanned them out
# to every party member with no coercion, length check, or throttle --
# a room-wide amplification / event-loop DoS primitive. Values below
# match typical chat-service limits: 2 KiB per message and 5 msgs / 3s
# per sid (bursts of 5 allowed, sustained rate capped).
_CHAT_MAX_LEN = 2048


def register(ctx):
    sio = ctx["sio"]
    logger = ctx["logger"]
    party_manager = ctx["party_manager"]
    rate_limiter = ctx.get("rate_limiter")
    config = ctx.get("config")

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

        if party and party.has_sid(sid):
            # Every other limiter honours the master switch -- rate_limit.py:155,
            # admin.py:68, avatar.py:163, connection.py:208. Chat was the one
            # site that did not, which mattered little while the limit dropped
            # messages silently, and matters now: the notice below disables the
            # composer, so an operator with ENABLE_RATE_LIMITING off would watch
            # a limit they had switched off block their users.
            if rate_limiter and config and config.ENABLE_RATE_LIMITING:
                limit, window = parse_rate(getattr(config, "RATE_LIMIT_CHAT", "5 per 3 seconds"))
                decision = rate_limiter.check(f"chat:{sid}", limit, window)
                if not decision.allowed:
                    logger.debug(f"Chat message dropped: sid={sid} rate-limited in {party_id}")
                    await sio.emit(
                        "rate_limited",
                        {
                            "action": "chat",
                            "message": (
                                "Message not sent: chat limit reached. "
                                f"Try again in {decision.retry_after} seconds."
                            ),
                            "retry_after": decision.retry_after,
                            "request_id": data.get("request_id"),
                        },
                        to=sid,
                    )
                    return
            username = party.username_for_sid(sid)
            # Look up the sender's persistent avatar identity so the
            # client can render their chosen avatar instead of the
            # username-derived monsterid.
            client_id = party.sid_client_ids.get(sid)
            participant = party.participants.get(client_id) if client_id else None
            avatar_uuid = participant.avatar_uuid if participant else None
            await sio.emit(
                "chat_message",
                {
                    "username": username,
                    "avatar_uuid": avatar_uuid,
                    "message": message,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                room=party_id,
            )

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
        caller_client_id = party.sid_client_ids.get(sid)
        if caller_client_id != party.host_client_id:
            logger.debug(f"toggle_library REJECTED: sid={sid} is not host of {party_id}")
            return

        logger.info(f"Library toggled in party {party_id}: show={show}")
        await sio.emit("toggle_library", {"show": show}, room=party_id)
