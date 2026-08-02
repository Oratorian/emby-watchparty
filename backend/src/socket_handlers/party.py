"""Party handlers: join_party, leave_party, join_vote + late-joiner vote lifecycle"""

import asyncio
import time
from datetime import datetime

from backend.src.domain import JoinVote
from backend.src.quality import DEFAULT_QUALITY_ID
from backend.src.utils import generate_random_username


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    config = ctx['config']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    token_manager = ctx['token_manager']
    restart_video_from_beginning = ctx['restart_video_from_beginning']
    create_user_stream = ctx.get('create_user_stream')
    session_secret = ctx.get('session_secret')

    def _cookie_session(environ):
        """Read the party-bound session cookie off the raw ASGI environ.

        Same decoder as connection.py:_decode_session; broken out here
        so join_party can gate the eviction path on cookie proof.
        Returns the decoded session dict or None. Session cookie name +
        max-age are kept in sync with SessionMiddleware config in
        backend/app.py.
        """
        if not session_secret:
            return None
        raw = environ.get("HTTP_COOKIE", "")
        if not raw:
            return None
        # Reuse connection.py helpers rather than duplicating parse
        # logic; a stray drift between the two parsers would silently
        # break auth on one side.
        from backend.src.socket_handlers.connection import _decode_session
        return _decode_session(environ, session_secret)

    # -------------------------------------------------------------------------
    # Late-joiner vote helpers
    # -------------------------------------------------------------------------

    def _vote_usernames(party, sids):
        """Convert a collection of sids to a list of display usernames."""
        return [party.users.get(s, "?") for s in sids]

    def _current_party_time(party):
        """Return the server's current best estimate of playback position."""
        playback_state = party.playback_state
        current_time = playback_state.time
        if playback_state.playing and playback_state.last_update:
            try:
                last_update = datetime.fromisoformat(playback_state.last_update)
                elapsed = (datetime.now() - last_update).total_seconds()
                if 0 < elapsed < 30:
                    current_time += elapsed
            except Exception:
                pass
        return current_time

    async def _replace_sid(party, old_sid, new_sid, username, client_id=None,
                     avatar_uuid=None):
        """Move all sid-keyed party state from an old socket to a new one."""
        commit = await party_manager.replace_socket(
            party.id,
            old_sid=old_sid,
            new_sid=new_sid,
            username=username,
            client_id=client_id,
            avatar_uuid=avatar_uuid,
        )
        if commit is None:
            return
        old_stream = commit.stream
        current_video = commit.current_video
        if old_stream and old_stream.play_session_id and current_video:
            await emby_client.report_playback_stopped(
                item_id=current_video["item_id"],
                media_source_id=old_stream.media_source_id,
                play_session_id=old_stream.play_session_id,
                position_seconds=commit.playback_time,
                run_time_seconds=current_video.get("run_time_seconds"),
                access_token=commit.host_access_token,
                user_id=commit.host_user_id,
            )
            await emby_client.stop_active_encodings(
                play_session_id=old_stream.play_session_id,
                access_token=commit.host_access_token,
            )

    async def _build_rejoin_video(party, party_id, sid):
        """Create a fresh per-user stream for a known participant rejoining."""
        current_video = party.current_video
        if not current_video or not create_user_stream:
            return None

        current_time = _current_party_time(party)
        stream = await create_user_stream(
            party, party_id, sid, current_video["item_id"], None,
            audio_index=None, subtitle_index=None,
            quality=current_video.get("quality", DEFAULT_QUALITY_ID),
            start_seconds=current_time,
            # Lock the late-joiner to the same Emby version the rest of
            # the party is watching. Without this they'd silently get
            # Emby's default source (issue #43).
            media_source_id=current_video.get("media_source_id"),
        )
        if not stream:
            return None

        stream_url = stream.stream_url_base
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = token_manager.get_or_create(party_id, sid)
            if user_token:
                stream_url += f"&token={user_token}"

        return {
            "item_id": current_video.get("item_id"),
            "title": current_video.get("title"),
            "overview": current_video.get("overview"),
            "stream_url": stream_url,
            "audio_index": stream.audio_index,
            "subtitle_index": stream.subtitle_index,
            "media_source_id": stream.media_source_id,
            "selected_by": current_video.get("selected_by"),
            "quality": stream.quality or current_video.get(
                "quality", DEFAULT_QUALITY_ID
            ),
            # Carry the binge-watching metadata so a late joiner sees
            # the same control-strip button visibility and library
            # NEXT badge as the rest of the room.
            "item_type": current_video.get("item_type"),
            "series_id": current_video.get("series_id"),
            "season_id": current_video.get("season_id"),
            "episode_index": current_video.get("episode_index"),
            "next_item_id": current_video.get("next_item_id"),
            "next_item_title": current_video.get("next_item_title"),
        }, current_time

    def _votes_by_username(party, votes_dict):
        """Convert {sid: "yes"|"no"} to {username: "yes"|"no"} for client broadcasts."""
        return {party.users.get(sid, "?"): vote for sid, vote in votes_dict.items()}

    async def _broadcast_vote_update(party, party_id):
        """Emit the current vote state to the whole party room."""
        pj = party.pending_join
        if not pj:
            return
        remaining = len(pj.eligible_voters) - len(pj.votes)
        await sio.emit("join_vote_update", {
            "votes": _votes_by_username(party, pj.votes),
            "remaining": remaining,
        }, room=party_id)

    async def _resolve_vote_pass(party_id):
        """Vote passed: restart the video from the beginning for all users
        (including the late joiner), and promote the late joiner to a full
        party member."""
        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.pending_join
        if not pj:
            return

        late_sid = pj.sid
        late_username = pj.username
        client_id = pj.client_id or f"sid:{late_sid}"

        # Cancel the watchdog if still active (prevent it firing after resolution)
        task = pj.timeout_task
        if task and not task.done():
            task.cancel()

        logger.info(f"Vote passed in party {party_id}: restarting for late joiner {late_username}")

        # Promote the late joiner to a full user so they participate in the
        # restart. Until now they were only in the Socket.IO room but NOT in
        # party.users.
        await _replace_sid(party, None, late_sid, late_username, client_id)

        # Clear pending_join BEFORE emitting resolution so a simultaneous join
        # attempt from another user sees no active vote.
        await party_manager.clear_join_vote(party_id)

        # Tell everyone the vote resolved (they dismiss the modal / waiting room)
        await sio.emit("join_vote_resolved", {"result": "pass"}, room=party_id)

        # Emit user_joined so existing clients update their participant list
        await sio.emit("user_joined", {
            "username": late_username,
            "users": list(party.users.values()),
            "members": party_manager.members_list(party_id),
            "rejoin": False,
        }, room=party_id)

        # Restart the current video from segment 0. Use the existing
        # current_video metadata to keep the same title/item_id.
        cv = party.current_video
        if not cv:
            logger.warning(f"Vote passed but no current_video in party {party_id}")
            return

        success = await restart_video_from_beginning(
            party, party_id,
            selector_client_id=cv.get("selected_by"),
            item_id=cv["item_id"],
            item_name=cv.get("title", "Unknown"),
            item_overview=cv.get("overview", ""),
            # Preserve the chosen alternate version across the
            # vote-pass restart -- otherwise the post-vote re-pick
            # would silently drop back to Emby's default source.
            media_source_id=cv.get("media_source_id"),
        )
        if not success:
            logger.error(f"Failed to restart video after vote pass in party {party_id}")

    async def _resolve_vote_fail(party_id):
        """Vote failed: reject the late joiner and leave existing users undisturbed."""
        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.pending_join
        if not pj:
            return

        late_sid = pj.sid
        late_username = pj.username

        task = pj.timeout_task
        if task and not task.done():
            task.cancel()

        logger.info(f"Vote failed in party {party_id}: rejecting late joiner {late_username}")

        await party_manager.clear_join_vote(
            party_id,
            cooldown_seconds=config.LATE_JOIN_VOTE_COOLDOWN_SECONDS,
        )

        # Tell the room the vote failed (closes the modal)
        await sio.emit("join_vote_resolved", {"result": "fail"}, room=party_id)
        # Tell the late joiner specifically they were rejected
        await sio.emit("join_rejected", {
            "message": "The party declined your request to join."
        }, to=late_sid)
        # Evict them from the Socket.IO room
        try:
            await sio.leave_room(late_sid, party_id)
        except Exception:
            pass

    async def _apply_tiebreak(party_id):
        """Apply the selector tiebreak rule. Called when everyone has voted
        but no strict majority was reached, or when the timeout expires.

        - Selector voted yes -> pass
        - Selector voted no -> fail
        - Selector did not vote (disconnected or abstained) -> default fail
        """
        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.pending_join
        if not pj:
            return

        selector_sid = pj.selector_sid
        selector_vote = pj.votes.get(selector_sid) if selector_sid else None

        if selector_vote == "yes":
            logger.info(f"Tiebreak in {party_id}: selector said yes -> pass")
            await _resolve_vote_pass(party_id)
        else:
            logger.info(f"Tiebreak in {party_id}: selector said {selector_vote or 'nothing'} -> fail")
            await _resolve_vote_fail(party_id)

    async def _check_vote_resolution(party_id):
        """Check if the vote can be resolved now.

        Resolution cases:
        - Strict majority yes -> pass immediately
        - Strict majority no -> fail immediately
        - Everyone has voted but no strict majority -> apply tiebreak now
          (don't make users wait for the full timeout)
        - Otherwise keep waiting for more votes or the timeout watchdog.
        """
        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.pending_join
        if not pj:
            return

        yes_count = sum(1 for v in pj.votes.values() if v == "yes")
        no_count = sum(1 for v in pj.votes.values() if v == "no")
        total_votes = yes_count + no_count
        eligible = len(pj.eligible_voters)
        threshold = eligible // 2  # strict majority means > threshold

        if yes_count > threshold:
            await _resolve_vote_pass(party_id)
        elif no_count > threshold:
            await _resolve_vote_fail(party_id)
        elif total_votes >= eligible:
            # Every eligible voter has voted but no strict majority was
            # reached (classic tie, e.g. 1-1 in a 2-user party). Apply
            # the selector tiebreak right away instead of making everyone
            # wait for the full timeout.
            await _apply_tiebreak(party_id)
        # Otherwise keep waiting. The watchdog handles timeouts/abstains.

    async def _vote_timeout_watchdog(party_id, timeout_seconds):
        """Wait timeout_seconds, then apply the selector tiebreak rule.

        If the vote was already resolved early (by majority or tie-at-all-voted),
        pending_join will be None and we return without doing anything.
        """
        try:
            await asyncio.sleep(timeout_seconds)
        except asyncio.CancelledError:
            return

        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.pending_join
        if not pj:
            return  # Already resolved

        logger.info(f"Vote timeout in party {party_id}")
        # Drop our own task handle before resolving. _resolve_vote_pass /
        # _resolve_vote_fail cancel pj.timeout_task to stop a pending
        # watchdog, but here the watchdog IS the caller. Cancelling the
        # running task would raise CancelledError at the next await (the
        # join_vote_resolved emit), so the resolution would never reach the
        # clients and the modal would hang forever.
        await party_manager.set_join_vote_task(party_id, None)
        await _apply_tiebreak(party_id)

    async def _start_late_join_vote(party, party_id, late_sid, late_username, client_id=None):
        """Initialize a vote for a new late joiner. Returns True if the vote
        started, False if a vote was already in progress."""
        if party.pending_join is not None:
            return False

        # Snapshot eligible voters: everyone currently in the party
        eligible_voters = set(party.users.keys())
        # current_video.selected_by holds the selector's persistent client_id,
        # but votes are keyed by sid. Resolve the selector's *current* sid so
        # the tiebreak rule can find their vote.
        selector_sid = None
        cv = party.current_video
        if cv:
            selector_client_id = cv.get("selected_by")
            if selector_client_id:
                for s, cid in party.sid_client_ids.items():
                    if cid == selector_client_id:
                        selector_sid = s
                        break

        timeout_seconds = getattr(config, "LATE_JOIN_VOTE_TIMEOUT_SECONDS", 20)

        vote = JoinVote(
            sid=late_sid,
            username=late_username,
            client_id=client_id,
            eligible_voters=eligible_voters,
            selector_sid=selector_sid,
        )
        if not await party_manager.begin_join_vote(party_id, vote):
            return False

        # Put the late joiner into the Socket.IO room so they receive
        # vote-progress broadcasts, but do NOT add them to party.users
        # yet -- they are held in a pending state.
        await sio.enter_room(late_sid, party_id)

        eligible_names = _vote_usernames(party, eligible_voters)
        required_majority = (len(eligible_voters) // 2) + 1

        # Notify existing users (excluding the late joiner) that a vote started
        await sio.emit("join_vote_started", {
            "username": late_username,
            "timeout_seconds": timeout_seconds,
            "eligible_voters": eligible_names,
            "required_majority": required_majority,
        }, room=party_id, skip_sid=late_sid)

        # Notify the late joiner that they are in the waiting room
        await sio.emit("join_vote_pending", {
            "timeout_seconds": timeout_seconds,
            "eligible_voters": eligible_names,
            "required_majority": required_majority,
        }, to=late_sid)

        # Spawn the timeout watchdog
        task = asyncio.create_task(_vote_timeout_watchdog(party_id, timeout_seconds))
        if not await party_manager.set_join_vote_task(party_id, task):
            task.cancel()
            return False

        logger.info(
            f"Started late join vote in party {party_id} for {late_username} "
            f"(eligible={len(eligible_voters)}, timeout={timeout_seconds}s)"
        )
        return True

    async def _handle_disconnect_from_vote(party, party_id, sid):
        """Handle a disconnect or leave during an active vote.

        Called from both disconnect and leave_party paths. Modifies
        eligible_voters/votes and re-checks resolution if needed.
        """
        pj = party.pending_join
        if not pj:
            return

        # Case 1: the disconnecting user IS the late joiner
        if pj.sid == sid:
            logger.info(f"Late joiner {pj.username} disconnected mid-vote in {party_id}")
            # Cancel the watchdog
            task = pj.timeout_task
            if task and not task.done():
                task.cancel()
            await party_manager.clear_join_vote(
                party_id,
                cooldown_seconds=config.LATE_JOIN_VOTE_COOLDOWN_SECONDS,
            )
            # Apply cooldown to prevent spam (same user immediately rejoining
            # and spawning another vote, e.g. after a force-reload)
            # Tell existing users the vote was cancelled because the joiner left
            await sio.emit("join_vote_resolved", {
                "result": "cancelled",
                "reason": "Late joiner left before the vote completed.",
            }, room=party_id)
            return

        # Case 2: the disconnecting user is an eligible voter
        if sid in pj.eligible_voters:
            await party_manager.remove_join_voter(party_id, sid)

            # If nobody is left to vote, fail the vote
            if not pj.eligible_voters:
                await _resolve_vote_fail(party_id)
                return

            await _broadcast_vote_update(party, party_id)
            await _check_vote_resolution(party_id)

    # Expose vote helpers in ctx so connection.py can reuse them during disconnect
    ctx['handle_disconnect_from_vote'] = _handle_disconnect_from_vote

    # -------------------------------------------------------------------------
    # Event handlers
    # -------------------------------------------------------------------------

    @sio.on("join_party")
    async def handle_join_party(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        username = data.get("username", "").strip()
        client_id = str(data.get("client_id", "")).strip()
        avatar_uuid = data.get("avatar_uuid")
        if isinstance(avatar_uuid, str):
            avatar_uuid = avatar_uuid.strip() or None
        else:
            avatar_uuid = None

        if not username:
            username = generate_random_username()
            logger.info(f"Generated random username: {username}")
        if not client_id:
            client_id = f"sid:{sid}"

        if not party_manager.exists(party_id):
            logger.warning(f"Join failed: party {party_id} not found (user: {username})")
            await sio.emit("error", {"message": "Watch party not found"}, to=sid)
            return

        party = party_manager.get(party_id)
        participants = party.participants
        sid_client_ids = party.sid_client_ids
        known_participant = client_id in participants
        rejoin = known_participant
        existing_participant = participants.get(client_id)
        old_sid = existing_participant.sid if existing_participant else None

        if known_participant:
            if old_sid and old_sid != sid:
                await sio.leave_room(old_sid, party_id)
                logger.info(f"Reattached participant {username} in {party_id}: {old_sid} -> {sid}")
            await _replace_sid(party, old_sid, sid, username, client_id, avatar_uuid)
        else:
            # Historically this evicted any existing member with a
            # matching display name (with a different client_id) so
            # duplicate-tab / lost-client_id refreshes would land on
            # their seat. But username is a public string and there is
            # no party password, so anyone knowing (party code, member
            # name) could kick the real member off their seat, inherit
            # their ready_check membership, and DoS their Emby transcode
            # via _replace_sid's teardown.
            #
            # Gate the eviction on a valid session cookie carrying the
            # SAME client_id as the joiner. HTTP /api/party/<id>/join
            # is the only route that mints those cookies, and it stores
            # the caller-supplied client_id verbatim -- so a legitimate
            # duplicate-tab / same-browser user matches, but a random
            # attacker with just the party code + username does not.
            environ = sio.get_environ(sid) or {}
            cookie_session = _cookie_session(environ)
            cookie_client_id = cookie_session.get("client_id") if cookie_session else None
            cookie_party_id = (cookie_session.get("party_id") or "").upper() if cookie_session else ""
            same_browser = (
                cookie_client_id == client_id and cookie_party_id == party_id
            )
            for stale_sid, existing_name in list(party.users.items()):
                if existing_name == username and stale_sid != sid:
                    if not same_browser:
                        logger.warning(
                            f"Join eviction REJECTED in {party_id}: "
                            f"caller sid={sid} lacks session-cookie proof "
                            f"for username '{username}'; refusing to evict "
                            f"stale_sid={stale_sid}"
                        )
                        await sio.emit("error", {
                            "message": (
                                "That username is already in use. Pick "
                                "another display name."
                            )
                        }, to=sid)
                        return
                    stale_client_id = sid_client_ids.get(stale_sid)
                    if stale_client_id:
                        participants.pop(stale_client_id, None)
                    await sio.leave_room(stale_sid, party_id)
                    await _replace_sid(
                        party, stale_sid, sid, username, client_id, avatar_uuid
                    )
                    rejoin = True
                    logger.info(f"Evicted stale session {stale_sid} for {username}")
                    break

        # Check max users (count includes any pending late joiner)
        current_count = len(party.users)
        if party.pending_join:
            current_count += 1
        if not rejoin and config.MAX_USERS_PER_PARTY > 0 and current_count >= config.MAX_USERS_PER_PARTY:
            logger.warning(f"Party {party_id} is full")
            await sio.emit("error", {"message": f"Party is full (max {config.MAX_USERS_PER_PARTY} users)"}, to=sid)
            return

        # -----------------------------------------------------------------
        # Late joiner vote flow
        # -----------------------------------------------------------------
        vote_enabled = getattr(config, "LATE_JOIN_VOTE_ENABLED", True)
        has_active_video = party.current_video is not None
        has_existing_users = len(party.users) > 0

        if not rejoin and vote_enabled and has_active_video and has_existing_users:
            # Don't start a second vote on top of an active one
            if party.pending_join is not None:
                logger.info(f"Join rejected: vote already in progress in party {party_id}")
                await sio.emit("join_rejected", {
                    "message": "Another user is currently waiting for approval. Try again shortly.",
                }, to=sid)
                return

            # Enforce post-vote cooldown. Prevents a malicious user from
            # spamming /party/<id> to repeatedly pop vote modals on the
            # existing watchers.
            cooldown_until = party.join_cooldown_until or 0
            now = time.time()
            if cooldown_until > now:
                wait_seconds = int(cooldown_until - now) + 1
                logger.info(
                    f"Join rejected: cooldown active in party {party_id} "
                    f"({wait_seconds}s remaining, user: {username})"
                )
                await sio.emit("join_rejected", {
                    "message": (
                        f"The party is on cooldown after a recent vote. "
                        f"Try again in {wait_seconds} seconds."
                    ),
                    "retry_after": wait_seconds,
                }, to=sid)
                return

            # Start the vote -- this puts the late joiner into the Socket.IO
            # room but does NOT add them to party.users yet.
            started = await _start_late_join_vote(party, party_id, sid, username, client_id)
            if started:
                return  # Vote flow takes over; no immediate sync_state

        # -----------------------------------------------------------------
        # Normal join path (no active video, vote disabled, or empty party
        # with a stale current_video from the static-session edge case)
        # -----------------------------------------------------------------
        await sio.enter_room(sid, party_id)
        await _replace_sid(
            party,
            old_sid if known_participant else sid,
            sid,
            username,
            client_id,
            avatar_uuid,
        )

        # Fast host-rejoin path. If a grace task is pending because this
        # client_id was hosting and just dropped, cancel it and tell the
        # room the party is UNLOCKED again. No re-authentication needed.
        try_host_reclaim = ctx.get('try_host_reclaim')
        if try_host_reclaim:
            await try_host_reclaim(party_id, client_id, sid)

        await sio.emit("user_joined", {
            "username": username,
            "users": list(party.users.values()),
            "members": party_manager.members_list(party_id),
            "rejoin": rejoin,
        }, room=party_id)

        # Send a sync_state. If video is active, create a fresh per-user
        # stream at the current party position so reload/rejoin can resume
        # without triggering the late-join vote or restarting everyone.
        current_video = None
        playback_state = party.playback_state.to_wire()
        if party.current_video:
            rejoin_video = await _build_rejoin_video(party, party_id, sid)
            if rejoin_video:
                current_video, current_time = rejoin_video
                playback_state["time"] = current_time
            else:
                cv = party.current_video
                current_video = {
                    "item_id": cv.get("item_id"),
                    "title": cv.get("title"),
                    "overview": cv.get("overview"),
                    "selected_by": cv.get("selected_by"),
                    "item_type": cv.get("item_type"),
                    "series_id": cv.get("series_id"),
                    "season_id": cv.get("season_id"),
                    "episode_index": cv.get("episode_index"),
                    "next_item_id": cv.get("next_item_id"),
                    "next_item_title": cv.get("next_item_title"),
                }

        # Pending auto-advance state. A user who refreshes / rejoins
        # while the binge countdown is running should see the modal +
        # Cancel button. Without this block their client hydrates with
        # pendingAutoAdvance=null, so the modal never renders and the
        # watchdog fires unattended -- the selector loses the ability
        # to cancel the advance because they never see it. Fields
        # mirror the auto_advance_pending event so the frontend store
        # (party.ts) can reuse the same hydration path.
        pending_advance_payload = None
        pending = party.pending_auto_advance
        if pending:
            deadline = pending.deadline
            countdown_seconds = None
            if deadline:
                try:
                    remaining = (
                        datetime.fromisoformat(deadline) - datetime.now()
                    ).total_seconds()
                    countdown_seconds = max(0, int(remaining))
                except Exception:
                    countdown_seconds = None
            pending_advance_payload = {
                "next_item_id": pending.next_item_id,
                "next_title": pending.next_title,
                "next_index_number": pending.next_index_number,
                "total_episodes": max(
                    (ep.get("IndexNumber") or 0)
                    for ep in (party.episode_list or [])
                ) if party.episode_list else 0,
                "deadline": deadline,
                "countdown_seconds": countdown_seconds,
            }

        await sio.emit("sync_state", {
            "current_video": current_video,
            "playback_state": playback_state,
            # Binge-watching state is part of the joiner's view of the
            # room: the control-strip button should render in the right
            # state from the first frame instead of flickering when a
            # follow-up event lands. available is read from the live
            # admin toggle so flipping it off in /admin is reflected on
            # the very next join.
            "binge_watch": {
                "available": bool(config.BINGE_WATCH_ENABLED),
                "active": bool(party.binge_watch_active),
            },
            "pending_auto_advance": pending_advance_payload,
        }, to=sid)

    @sio.on("join_vote")
    async def handle_join_vote(sid, data):
        """Vote submission from an eligible voter."""
        party_id = data.get("party_id", "").strip().upper()
        vote = data.get("vote")

        if vote not in ("yes", "no"):
            return

        party = party_manager.get(party_id)
        if not party:
            return

        pj = party.pending_join
        if not pj:
            logger.debug(f"Vote from {sid} ignored: no active vote in {party_id}")
            return

        if sid not in pj.eligible_voters:
            logger.debug(f"Vote from {sid} ignored: not an eligible voter in {party_id}")
            return

        # Record the vote (overwriting any previous vote from the same user)
        if not await party_manager.record_join_vote(party_id, sid, vote):
            return
        logger.debug(f"Vote recorded in {party_id}: {party.users.get(sid, sid)} -> {vote}")

        # Broadcast the updated tally and check for early resolution
        await _broadcast_vote_update(party, party_id)
        await _check_vote_resolution(party_id)

    @sio.on("leave_party")
    async def handle_leave_party(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        # If the leaving user is involved in an active vote, handle that first
        await _handle_disconnect_from_vote(party, party_id, sid)

        # Host leaving explicitly (clicked Leave). A disconnect gets a 5s grace
        # window for refresh-as-rejoin, but an explicit leave is intentional, so
        # transition the lock state now. This MUST run before the
        # sid_client_ids pop below, which erases the mapping used to identify
        # the host (and is why the disconnect handler alone could not catch an
        # explicit leave).
        departing_client_id = party.sid_client_ids.get(sid)
        if (
            departing_client_id
            and departing_client_id == party.host_client_id
            and party.host_left_at is None
        ):
            host_username = party.host_username or "?"
            pending = ctx.get("pending_host_clear", {})
            grace_task = pending.pop(party_id, None)
            if grace_task and not grace_task.done():
                grace_task.cancel()
            if party.current_video:
                # PLAYING-ONLY: keep the token so the in-flight stream finishes
                # for everyone else; a later video_ended/stop_video clears it.
                party_manager.mark_host_left(party_id)
                logger.info(
                    f"Host '{host_username}' left party {party_id} during "
                    f"playback -> PLAYING-ONLY"
                )
                await sio.emit("host_left", {
                    "previous_host": host_username,
                    "reason": "leave",
                    "playing_only": True,
                }, room=party_id, skip_sid=sid)
            else:
                party_manager.clear_host(party_id)
                logger.info(
                    f"Host '{host_username}' left party {party_id} (no playback) "
                    f"-> LOCKED"
                )
                await sio.emit("host_left", {
                    "previous_host": host_username,
                    "reason": "leave",
                }, room=party_id, skip_sid=sid)

        if sid in party.users:
            departure = await party_manager.depart_socket(
                party_id, sid, forget_participant=True
            )
            if departure is None:
                return
            username = departure.username or "Unknown"

            # Stop this user's individual transcode outside the party lock.
            user_stream = departure.stream
            current_video = departure.current_video
            if user_stream and user_stream.play_session_id and current_video:
                await emby_client.report_playback_stopped(
                    item_id=current_video["item_id"],
                    media_source_id=user_stream.media_source_id,
                    play_session_id=user_stream.play_session_id,
                    position_seconds=departure.playback_time,
                    run_time_seconds=current_video.get("run_time_seconds"),
                    access_token=departure.host_access_token,
                    user_id=departure.host_user_id,
                )
                await emby_client.stop_active_encodings(
                    play_session_id=user_stream.play_session_id,
                    access_token=departure.host_access_token,
                )
            token_manager.revoke_user(party_id, sid)

            await sio.leave_room(sid, party_id)
            if departure.all_ready:
                logger.info(f"All users ready in party {party_id} (after leave)")
                await sio.emit("all_ready", {
                        "time": departure.playback_time,
                        "playing": departure.playback_playing,
                    }, room=party_id)
                if departure.auto_play:
                    await sio.emit("play", {
                        "time": departure.playback_time,
                        "username": None,
                        "auto_binge": True,
                    }, room=party_id)
            elif departure.ready_names or departure.waiting_names:
                await sio.emit("ready_check_update", {
                    "ready": list(departure.ready_names),
                    "waiting": list(departure.waiting_names),
                }, room=party_id)

            await sio.emit("user_left", {
                "username": username,
                "users": list(party.users.values()),
                "members": party_manager.members_list(party_id),
            }, room=party_id)

            lifecycle = ctx.get("party_lifecycle")
            if lifecycle:
                await lifecycle.dissolve_if_empty(party_id)

    @sio.on("update_avatar")
    async def handle_update_avatar(sid, data):
        """Re-bind the caller's avatar_uuid and broadcast the new
        member roster so every connected client re-renders.

        Used after the avatar setup modal saves an upload, links a
        Gravatar, or recovers via a code. Without this, only a page
        refresh would pick up the new avatar.
        """
        party_id = data.get("party_id", "").strip().upper()
        new_uuid = data.get("avatar_uuid")
        if isinstance(new_uuid, str):
            new_uuid = new_uuid.strip() or None
        elif new_uuid is not None:
            return

        party = party_manager.get(party_id)
        if not party:
            return
        client_id = party.sid_client_ids.get(sid)
        if not client_id:
            return
        participant = party.participants.get(client_id)
        if not participant:
            return
        participant.avatar_uuid = new_uuid

        await sio.emit("members_update", {
            "members": party_manager.members_list(party_id),
        }, room=party_id)
