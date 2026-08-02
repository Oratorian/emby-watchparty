"""Connection handlers: connect, disconnect.

Adds party-bound session cookie validation on connect and host-leave
detection on disconnect (with a brief grace window so a refresh does
not collapse the party to LOCKED).
"""

import asyncio
import base64
import json
from datetime import datetime
from http.cookies import SimpleCookie

from itsdangerous import TimestampSigner, BadSignature
from socketio.exceptions import ConnectionRefusedError as SocketConnectionRefusedError

from backend.src.client_ip import resolve_client_ip
from backend.src.rate_limit import parse_rate


# Must stay in sync with the `session_cookie` kwarg passed to
# SessionMiddleware in backend/app.py; otherwise the socket handshake
# reads the wrong cookie name and _decode_session always returns None.
SESSION_COOKIE_NAME = "ewp_session"
SESSION_MAX_AGE = 14 * 24 * 60 * 60  # Starlette SessionMiddleware default
HOST_GRACE_SECONDS = 5


def _decode_session(environ, secret):
    """Decode Starlette's signed session cookie, or None.

    Mirrors `starlette.middleware.sessions.SessionMiddleware` so the
    handshake can read the same cookie HTTP routes use.
    """
    if not secret:
        return None
    raw_cookie = environ.get("HTTP_COOKIE", "")
    if not raw_cookie:
        return None
    cookies = SimpleCookie()
    cookies.load(raw_cookie)
    morsel = cookies.get(SESSION_COOKIE_NAME)
    if not morsel:
        return None
    try:
        signer = TimestampSigner(str(secret))
        data = signer.unsign(morsel.value, max_age=SESSION_MAX_AGE)
        return json.loads(base64.b64decode(data))
    except (BadSignature, ValueError, json.JSONDecodeError):
        return None


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    token_manager = ctx.get('token_manager')
    session_secret = ctx.get('session_secret')
    rate_limiter = ctx.get('rate_limiter')
    config = ctx.get('config')

    # Keyed by party_id: the asyncio task that will fire host-cleanup
    # once the grace window expires. Surfaced via ctx so party.py can
    # cancel pending tasks on host rejoin.
    pending_host_clear: dict[str, asyncio.Task] = {}
    ctx['pending_host_clear'] = pending_host_clear

    async def _clear_host_after_grace(party_id, client_id, username):
        """Fire HOST_GRACE_SECONDS after the host's sid drops.

        Three outcomes:
        - Host's `client_id` reappeared in the party (refresh / reconnect):
          clear host_left_at, emit `host_reclaimed`.
        - Host did not return, no current video: full clear -> LOCKED.
        - Host did not return, video is active: stay PLAYING-ONLY (keep
          the token so HLS can finish the in-flight stream). The token
          is wiped later by playback.py when the video ends.
        """
        try:
            await asyncio.sleep(HOST_GRACE_SECONDS)
        except asyncio.CancelledError:
            return

        party = party_manager.get(party_id)
        if not party:
            pending_host_clear.pop(party_id, None)
            return

        # Host changed (someone else logged in during the grace window)
        # or already restored by a fast rejoin. Drop the task quietly.
        if party.host_client_id != client_id:
            pending_host_clear.pop(party_id, None)
            return
        if party.host_left_at is None:
            pending_host_clear.pop(party_id, None)
            return

        sid_client_ids = party.sid_client_ids
        if client_id in sid_client_ids.values():
            party.host_left_at = None
            pending_host_clear.pop(party_id, None)
            logger.info(
                f"Host '{username}' rejoined party {party_id} within grace; "
                f"reclaimed UNLOCKED"
            )
            await sio.emit(
                "host_reclaimed", {"host_username": username}, room=party_id
            )
            return

        if not party.current_video:
            party_manager.clear_host(party_id)
            logger.info(
                f"Host '{username}' left party {party_id} (no playback) -> LOCKED"
            )
            await sio.emit(
                "host_left",
                {"previous_host": username, "reason": "disconnect"},
                room=party_id,
            )
        else:
            logger.info(
                f"Host '{username}' left party {party_id} during playback "
                f"-> PLAYING-ONLY"
            )
            await sio.emit(
                "host_left",
                {
                    "previous_host": username,
                    "reason": "disconnect",
                    "playing_only": True,
                },
                room=party_id,
            )

        pending_host_clear.pop(party_id, None)

    async def _try_host_reclaim(party_id: str, client_id: str, sid: str) -> bool:
        """Cancel a pending grace task when the host's client_id rejoins.

        Called from party.py after `_replace_sid` has migrated state to
        the new sid. Returns True iff a reclaim event was emitted.

        Auth model: client_id alone is NOT proof of identity, because
        the host's client_id is broadcast in the `host_changed` event to
        every party member. Reclaim additionally requires the socket to
        carry a valid session cookie signed by this server for the same
        party_id + client_id. HTTP `/api/party/<id>/join` is the only
        route that mints such a cookie, so a co-attendee who scraped
        the host's client_id from the socket stream still can't reclaim
        without the signed cookie.
        """
        party = party_manager.get(party_id)
        if not party:
            return False
        if party.host_client_id != client_id:
            return False
        if party.host_left_at is None:
            return False

        # Session-cookie proof gate.
        environ = sio.get_environ(sid) or {}
        session = _decode_session(environ, session_secret)
        if not session:
            logger.warning(
                f"Host reclaim REJECTED for {party_id}: sid={sid} has no "
                f"valid session cookie (client_id {client_id[:8]}... may "
                f"be scraped from host_changed broadcast)"
            )
            return False
        cookie_party = (session.get("party_id") or "").upper()
        cookie_client = session.get("client_id")
        if cookie_party != party_id or cookie_client != client_id:
            logger.warning(
                f"Host reclaim REJECTED for {party_id}: cookie "
                f"party={cookie_party}/client={cookie_client and cookie_client[:8]} "
                f"does not match rejoin party/client"
            )
            return False

        task = pending_host_clear.pop(party_id, None)
        if task and not task.done():
            task.cancel()

        party.host_left_at = None
        username = party.host_username or "?"
        logger.info(
            f"Host '{username}' reclaimed party {party_id} via fast rejoin"
        )
        await sio.emit(
            "host_reclaimed", {"host_username": username}, room=party_id
        )
        return True

    ctx['try_host_reclaim'] = _try_host_reclaim

    @sio.event
    async def connect(sid, environ, auth=None):
        if rate_limiter and config and config.ENABLE_RATE_LIMITING:
            peer_ip = environ.get("REMOTE_ADDR", "0.0.0.0")
            client_ip = resolve_client_ip(
                peer_ip,
                environ.get("HTTP_X_FORWARDED_FOR", ""),
                config.TRUSTED_PROXY_CIDRS,
            )
            limit, window = parse_rate(config.RATE_LIMIT_SOCKET_CONNECTIONS)
            decision = rate_limiter.check(f"socket-connect:{client_ip}", limit, window)
            if not decision.allowed:
                raise SocketConnectionRefusedError("rate_limited")
        # The connect step is best-effort. We log what the cookie looks
        # like for diagnostics but never refuse the socket: party-bound
        # routing happens via the `join_party` event which carries an
        # explicit party_id, and HTTP routes have their own session
        # gate. Refusing connects based on a stale cookie pointing at a
        # deleted party (common after navigating between parties or a
        # static-session reset) just leaves the frontend silently
        # un-joinable, which is a worse failure mode than letting an
        # extra cookieless connect through.
        session = _decode_session(environ, session_secret)
        if session and session.get("party_id") and session.get("client_id"):
            party_id = session["party_id"].upper()
            if party_manager.exists(party_id):
                logger.info(
                    f"Socket connected: {sid} -> party {party_id} "
                    f"(client {session['client_id'][:8]}...)"
                )
            else:
                logger.debug(
                    f"Socket {sid} carries stale party cookie ({party_id} "
                    f"not found); waiting for join_party to rebind"
                )
        else:
            logger.debug(f"Socket connect with no party-bound cookie: {sid}")

        await sio.emit("connected", {"sid": sid}, to=sid)

    @sio.event
    async def disconnect(sid):
        logger.info(f"Client disconnected: {sid}")
        handle_disconnect_from_vote = ctx.get('handle_disconnect_from_vote')

        for party_id, party in list(party_manager.get_all().items()):
            # Host-leave detection runs before the rest of the cleanup
            # so the grace task is scheduled even when the user's
            # presence in party.users has already been pruned.
            sid_client_ids = party.sid_client_ids
            departing_client_id = sid_client_ids.get(sid)
            host_client_id = party.host_client_id
            if (
                host_client_id
                and departing_client_id == host_client_id
                and party.host_left_at is None
            ):
                username = party.host_username or "?"
                party_manager.mark_host_left(party_id)
                old_task = pending_host_clear.get(party_id)
                if old_task and not old_task.done():
                    old_task.cancel()
                pending_host_clear[party_id] = asyncio.create_task(
                    _clear_host_after_grace(party_id, host_client_id, username)
                )
                logger.info(
                    f"Host '{username}' disconnected from {party_id}; "
                    f"grace timer started ({HOST_GRACE_SECONDS}s)"
                )

            # Handle late-joiner vote cleanup (the disconnecting user may be
            # the pending late joiner, or an eligible voter whose absence
            # changes the majority math).
            if party.pending_join and handle_disconnect_from_vote:
                pj = party.pending_join
                if pj["sid"] == sid or sid in pj.get("eligible_voters", set()):
                    await handle_disconnect_from_vote(party, party_id, sid)

            if sid in party.users:
                username = party.users[sid]

                # Stop this user's individual transcode
                user_stream = party.user_streams.get(sid)
                if user_stream and user_stream.get("play_session_id") and party.current_video:
                    current_time = party.playback_state.time
                    access_token = party.host_access_token
                    user_id = party.host_user_id
                    await emby_client.report_playback_stopped(
                        item_id=party.current_video["item_id"],
                        media_source_id=user_stream["media_source_id"],
                        play_session_id=user_stream["play_session_id"],
                        position_seconds=current_time,
                        run_time_seconds=party.current_video.get("run_time_seconds"),
                        access_token=access_token,
                        user_id=user_id,
                    )
                    await emby_client.stop_active_encodings(
                        play_session_id=user_stream["play_session_id"],
                        access_token=access_token,
                    )
                party.user_streams.pop(sid, None)
                if token_manager:
                    token_manager.revoke_user(party_id, sid)

                del party.users[sid]
                party.sid_client_ids.pop(sid, None)
                if sid in party.drift_strikes:
                    del party.drift_strikes[sid]

                # Remove from any active ready check so we don't wait forever
                # for a signal from a disconnected client
                rc = party.ready_check
                if rc and rc.active:
                    rc.expected_sids.discard(sid)
                    rc.ready_sids.discard(sid)
                    if rc.ready_sids >= rc.expected_sids and rc.expected_sids:
                        party.ready_check = None
                        playback_state = party.playback_state
                        # Consume auto_play_after_ready flag exactly like
                        # _check_all_ready in playback.py does. Without
                        # this the binge auto-advance flow can complete
                        # its ready check via a disconnect, land the room
                        # on the next episode with playing=False, and
                        # leave the flag stale on the party dict where
                        # it inappropriately fires on a later manual
                        # select. Mirror the playback.py:326-348 logic
                        # to keep the two completion paths in lockstep.
                        auto_play_pending = party.auto_play_after_ready
                        party.auto_play_after_ready = False
                        if auto_play_pending:
                            playback_state.playing = True
                        if playback_state.playing:
                            playback_state.last_update = datetime.now().isoformat()
                        logger.info(f"All users ready in party {party_id} (after disconnect)")
                        await sio.emit("all_ready", {
                            "time": playback_state.time,
                            "playing": playback_state.playing,
                        }, room=party_id)
                        if auto_play_pending:
                            await sio.emit("play", {
                                "time": playback_state.time,
                                "username": None,
                                "auto_binge": True,
                            }, room=party_id)
                    elif not rc.expected_sids:
                        # No one left to wait for -- cancel the check entirely
                        party.ready_check = None
                        # And drop the auto-play flag so it doesn't leak
                        # into an unrelated future ready check.
                        party.auto_play_after_ready = False
                    else:
                        ready_names = [party.users.get(s, "?") for s in rc.ready_sids]
                        waiting_names = [party.users.get(s, "?") for s in rc.expected_sids - rc.ready_sids]
                        await sio.emit("ready_check_update", {
                            "ready": ready_names, "waiting": waiting_names,
                        }, room=party_id)

                await sio.emit(
                    "user_left",
                    {
                        "username": username,
                        "users": list(party.users.values()),
                        "members": party_manager.members_list(party_id),
                    },
                    room=party_id,
                    skip_sid=sid,
                )
                lifecycle = ctx.get("party_lifecycle")
                if lifecycle:
                    await lifecycle.dissolve_if_empty(party_id)
