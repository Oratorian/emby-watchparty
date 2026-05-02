"""Party handlers: join_party, leave_party, join_vote + late-joiner vote lifecycle"""

import asyncio
import time
from datetime import datetime
from backend.src.utils import generate_random_username


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    config = ctx['config']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    restart_video_from_beginning = ctx['restart_video_from_beginning']

    # -------------------------------------------------------------------------
    # Late-joiner vote helpers
    # -------------------------------------------------------------------------

    def _vote_usernames(party, sids):
        """Convert a collection of sids to a list of display usernames."""
        return [party["users"].get(s, "?") for s in sids]

    def _votes_by_username(party, votes_dict):
        """Convert {sid: "yes"|"no"} to {username: "yes"|"no"} for client broadcasts."""
        return {party["users"].get(sid, "?"): vote for sid, vote in votes_dict.items()}

    async def _broadcast_vote_update(party, party_id):
        """Emit the current vote state to the whole party room."""
        pj = party.get("pending_join")
        if not pj:
            return
        remaining = len(pj["eligible_voters"]) - len(pj["votes"])
        await sio.emit("join_vote_update", {
            "votes": _votes_by_username(party, pj["votes"]),
            "remaining": remaining,
        }, room=party_id)

    async def _resolve_vote_pass(party_id):
        """Vote passed: restart the video from the beginning for all users
        (including the late joiner), and promote the late joiner to a full
        party member."""
        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.get("pending_join")
        if not pj:
            return

        late_sid = pj["sid"]
        late_username = pj["username"]

        # Cancel the watchdog if still active (prevent it firing after resolution)
        task = pj.get("timeout_task")
        if task and not task.done():
            task.cancel()

        logger.info(f"Vote passed in party {party_id}: restarting for late joiner {late_username}")

        # Promote the late joiner to a full user so they participate in the
        # restart. Until now they were only in the Socket.IO room but NOT in
        # party["users"].
        party["users"][late_sid] = late_username
        party.setdefault("join_times", {})[late_sid] = datetime.now().isoformat()

        # Clear pending_join BEFORE emitting resolution so a simultaneous join
        # attempt from another user sees no active vote.
        party["pending_join"] = None

        # Tell everyone the vote resolved (they dismiss the modal / waiting room)
        await sio.emit("join_vote_resolved", {"result": "pass"}, room=party_id)

        # Emit user_joined so existing clients update their participant list
        await sio.emit("user_joined", {
            "username": late_username,
            "users": list(party["users"].values()),
        }, room=party_id)

        # Restart the current video from segment 0. Use the existing
        # current_video metadata to keep the same title/item_id.
        cv = party.get("current_video")
        if not cv:
            logger.warning(f"Vote passed but no current_video in party {party_id}")
            return

        success = await restart_video_from_beginning(
            party, party_id,
            selector_sid=cv.get("selected_by"),
            item_id=cv["item_id"],
            item_name=cv.get("title", "Unknown"),
            item_overview=cv.get("overview", ""),
        )
        if not success:
            logger.error(f"Failed to restart video after vote pass in party {party_id}")

    def _set_cooldown(party):
        """Apply the post-vote cooldown to block new join attempts for a
        short window. Used after failed/cancelled votes to prevent spam
        attacks where a malicious user keeps hitting /party/<id>."""
        cooldown = getattr(config, "LATE_JOIN_VOTE_COOLDOWN_SECONDS", 30)
        if cooldown > 0:
            party["join_cooldown_until"] = time.time() + cooldown

    async def _resolve_vote_fail(party_id):
        """Vote failed: reject the late joiner and leave existing users undisturbed."""
        party = party_manager.get(party_id)
        if not party:
            return
        pj = party.get("pending_join")
        if not pj:
            return

        late_sid = pj["sid"]
        late_username = pj["username"]

        task = pj.get("timeout_task")
        if task and not task.done():
            task.cancel()

        logger.info(f"Vote failed in party {party_id}: rejecting late joiner {late_username}")

        party["pending_join"] = None
        _set_cooldown(party)

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
        pj = party.get("pending_join")
        if not pj:
            return

        selector_sid = pj.get("selector_sid")
        selector_vote = pj["votes"].get(selector_sid) if selector_sid else None

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
        pj = party.get("pending_join")
        if not pj:
            return

        yes_count = sum(1 for v in pj["votes"].values() if v == "yes")
        no_count = sum(1 for v in pj["votes"].values() if v == "no")
        total_votes = yes_count + no_count
        eligible = len(pj["eligible_voters"])
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
        pj = party.get("pending_join")
        if not pj:
            return  # Already resolved

        logger.info(f"Vote timeout in party {party_id}")
        await _apply_tiebreak(party_id)

    async def _start_late_join_vote(party, party_id, late_sid, late_username):
        """Initialize a vote for a new late joiner. Returns True if the vote
        started, False if a vote was already in progress."""
        if party.get("pending_join") is not None:
            return False

        # Snapshot eligible voters: everyone currently in the party
        eligible_voters = set(party["users"].keys())
        selector_sid = None
        cv = party.get("current_video")
        if cv:
            selector_sid = cv.get("selected_by")

        timeout_seconds = getattr(config, "LATE_JOIN_VOTE_TIMEOUT_SECONDS", 20)

        party["pending_join"] = {
            "sid": late_sid,
            "username": late_username,
            "requested_at": datetime.now().isoformat(),
            "eligible_voters": eligible_voters,
            "votes": {},
            "selector_sid": selector_sid,
            "timeout_task": None,
        }

        # Put the late joiner into the Socket.IO room so they receive
        # vote-progress broadcasts, but do NOT add them to party["users"]
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
        party["pending_join"]["timeout_task"] = task

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
        pj = party.get("pending_join")
        if not pj:
            return

        # Case 1: the disconnecting user IS the late joiner
        if pj["sid"] == sid:
            logger.info(f"Late joiner {pj['username']} disconnected mid-vote in {party_id}")
            # Cancel the watchdog
            task = pj.get("timeout_task")
            if task and not task.done():
                task.cancel()
            party["pending_join"] = None
            # Apply cooldown to prevent spam (same user immediately rejoining
            # and spawning another vote, e.g. after a force-reload)
            _set_cooldown(party)
            # Tell existing users the vote was cancelled because the joiner left
            await sio.emit("join_vote_resolved", {
                "result": "cancelled",
                "reason": "Late joiner left before the vote completed.",
            }, room=party_id)
            return

        # Case 2: the disconnecting user is an eligible voter
        if sid in pj["eligible_voters"]:
            pj["eligible_voters"].discard(sid)
            pj["votes"].pop(sid, None)
            # If the selector left mid-vote, clear the tiebreak authority
            if pj.get("selector_sid") == sid:
                pj["selector_sid"] = None

            # If nobody is left to vote, fail the vote
            if not pj["eligible_voters"]:
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

        # Check max users (count includes any pending late joiner)
        current_count = len(party["users"])
        if party.get("pending_join"):
            current_count += 1
        if config.MAX_USERS_PER_PARTY > 0 and current_count >= config.MAX_USERS_PER_PARTY:
            logger.warning(f"Party {party_id} is full")
            await sio.emit("error", {"message": f"Party is full (max {config.MAX_USERS_PER_PARTY} users)"}, to=sid)
            return

        # -----------------------------------------------------------------
        # Late joiner vote flow
        # -----------------------------------------------------------------
        vote_enabled = getattr(config, "LATE_JOIN_VOTE_ENABLED", True)
        has_active_video = party.get("current_video") is not None
        has_existing_users = len(party["users"]) > 0

        if vote_enabled and has_active_video and has_existing_users:
            # Don't start a second vote on top of an active one
            if party.get("pending_join") is not None:
                logger.info(f"Join rejected: vote already in progress in party {party_id}")
                await sio.emit("join_rejected", {
                    "message": "Another user is currently waiting for approval. Try again shortly.",
                }, to=sid)
                return

            # Enforce post-vote cooldown. Prevents a malicious user from
            # spamming /party/<id> to repeatedly pop vote modals on the
            # existing watchers.
            cooldown_until = party.get("join_cooldown_until", 0) or 0
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
            # room but does NOT add them to party["users"] yet.
            started = await _start_late_join_vote(party, party_id, sid, username)
            if started:
                return  # Vote flow takes over; no immediate sync_state

        # -----------------------------------------------------------------
        # Normal join path (no active video, vote disabled, or empty party
        # with a stale current_video from the static-session edge case)
        # -----------------------------------------------------------------
        await sio.enter_room(sid, party_id)
        party["users"][sid] = username
        party.setdefault("join_times", {})[sid] = datetime.now().isoformat()

        await sio.emit("user_joined", {
            "username": username,
            "users": list(party["users"].values()),
        }, room=party_id)

        # Send a sync_state. If no video is playing, current_video is null
        # and the client shows the library browser. If a video is playing
        # and we reached this path (vote disabled), include the shared
        # metadata but NOT a per-user stream URL -- the vote-disabled path
        # is a best-effort fallback and exact alignment is not guaranteed.
        current_video = None
        if party.get("current_video"):
            cv = party["current_video"]
            current_video = {
                "item_id": cv.get("item_id"),
                "title": cv.get("title"),
                "overview": cv.get("overview"),
                "selected_by": cv.get("selected_by"),
            }

        await sio.emit("sync_state", {
            "current_video": current_video,
            "playback_state": party["playback_state"].copy(),
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

        pj = party.get("pending_join")
        if not pj:
            logger.debug(f"Vote from {sid} ignored: no active vote in {party_id}")
            return

        if sid not in pj["eligible_voters"]:
            logger.debug(f"Vote from {sid} ignored: not an eligible voter in {party_id}")
            return

        # Record the vote (overwriting any previous vote from the same user)
        pj["votes"][sid] = vote
        logger.debug(f"Vote recorded in {party_id}: {party['users'].get(sid, sid)} -> {vote}")

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

            await sio.leave_room(sid, party_id)
            del party["users"][sid]

            # Remove from any active ready check so we don't wait forever
            rc = party.get("ready_check")
            if rc and rc.get("active"):
                rc["expected_sids"].discard(sid)
                rc["ready_sids"].discard(sid)
                if rc["ready_sids"] >= rc["expected_sids"] and rc["expected_sids"]:
                    party["ready_check"] = None
                    playback_state = party.get("playback_state", {})
                    if playback_state.get("playing"):
                        playback_state["last_update"] = datetime.now().isoformat()
                    logger.info(f"All users ready in party {party_id} (after leave)")
                    await sio.emit("all_ready", {
                        "time": playback_state.get("time", 0),
                        "playing": playback_state.get("playing", False),
                    }, room=party_id)
                elif not rc["expected_sids"]:
                    party["ready_check"] = None
                else:
                    ready_names = [party["users"].get(s, "?") for s in rc["ready_sids"]]
                    waiting_names = [party["users"].get(s, "?") for s in rc["expected_sids"] - rc["ready_sids"]]
                    await sio.emit("ready_check_update", {
                        "ready": ready_names, "waiting": waiting_names,
                    }, room=party_id)

            await sio.emit("user_left", {
                "username": username,
                "users": list(party["users"].values()),
            }, room=party_id)
