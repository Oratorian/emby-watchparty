"""Playback handlers: select_video, stop_video, change_streams, video_ended, report_progress, stream_ready.

Identity model:
- `current_video.selected_by` is the **client_id** of the user who picked
  the video, not their current sid. client_ids survive page refreshes,
  so a selector who reloads still owns Stop Video.
- Every Emby call uses the **host's** access_token / user_id. When the
  host has fully left (token cleared) Emby-touching events refuse the
  request; the party is LOCKED.
- After a video ends or is stopped in the PLAYING-ONLY state, the
  stored host token is wiped (full LOCKED).
"""

import asyncio
from datetime import datetime, timedelta
from backend.src.quality import (
    DEFAULT_QUALITY_ID,
    normalise_quality_id,
    resolve_quality,
)


def register(ctx):
    sio = ctx['sio']
    emby_client = ctx['emby_client']
    config = ctx['config']
    logger = ctx['logger']
    party_manager = ctx['party_manager']
    token_manager = ctx['token_manager']

    def _client_id_for_sid(party, sid):
        """Look up the persistent client_id mapped to this socket sid."""
        return party.get("sid_client_ids", {}).get(sid)

    def _host_creds(party):
        """Return (access_token, user_id) for the party's current host."""
        return party.get("host_access_token"), party.get("host_user_id")

    def _find_next_episode(episode_list, current_index_number):
        """Return the episode dict with the smallest IndexNumber strictly
        greater than current_index_number, or None for end-of-season.
        Pulled out into a helper so the same logic drives both the
        binge auto-advance pick at video_ended AND the "next" hint
        pinned on current_video at selection time (used by the
        frontend NEXT badge on the library card so the host sees
        what's queued before the current episode ends).
        """
        if current_index_number is None or not episode_list:
            return None
        next_ep = None
        for ep in episode_list:
            ep_num = ep.get("IndexNumber")
            if ep_num is None or ep_num <= current_index_number:
                continue
            if next_ep is None or ep_num < next_ep.get("IndexNumber"):
                next_ep = ep
        return next_ep

    def _resolve_episode_context(party, item_id, access_token, user_id):
        """Look up Type / SeriesId / SeasonId / IndexNumber for the
        currently-selected item and (for Episodes) cache the season's
        full episode list on the party so video_ended can find "next"
        without re-querying Emby. Returns a dict with keys item_type,
        series_id, season_id, episode_index -- all may be None for
        non-Episode items or when Emby fails to return metadata.

        Episode list caching keys on season_id; switching to a different
        season's episode (or to a non-Episode item) clears the cache.
        """
        result = {
            "item_type": None, "series_id": None,
            "season_id": None, "episode_index": None,
            "index_number": None,
            # Precomputed "what plays after this" so the frontend NEXT
            # badge can render the moment binge is armed, not just
            # during the countdown window. None for movies, the last
            # episode in a season, or anything without IndexNumber.
            "next_item_id": None,
            "next_item_title": None,
        }
        if not user_id:
            party["episode_list"] = None
            party["episode_list_season_id"] = None
            return result

        details = emby_client.get_item_details(
            item_id, access_token=access_token, user_id=user_id,
        )
        if not details:
            party["episode_list"] = None
            party["episode_list_season_id"] = None
            return result

        item_type = details.get("Type")
        result["item_type"] = item_type
        if item_type != "Episode":
            party["episode_list"] = None
            party["episode_list_season_id"] = None
            return result

        series_id = details.get("SeriesId")
        # Emby exposes the season as ParentId for episodes; SeasonId is
        # also set but ParentId is the field used elsewhere in this
        # codebase for the immediate parent.
        season_id = details.get("SeasonId") or details.get("ParentId")
        result["series_id"] = series_id
        result["season_id"] = season_id

        if not season_id:
            party["episode_list"] = None
            party["episode_list_season_id"] = None
            return result

        # Cache hit: same season as last selection, reuse the list.
        if party.get("episode_list_season_id") != season_id or not party.get("episode_list"):
            episodes = emby_client.get_season_episodes(
                season_id, access_token=access_token, user_id=user_id,
            )
            items = episodes.get("Items", []) if episodes else []
            # Trim to the fields binge-watching needs; we don't want to
            # store full Emby payloads on long-lived party state.
            party["episode_list"] = [
                {
                    "Id": ep.get("Id"),
                    "Name": ep.get("Name"),
                    "IndexNumber": ep.get("IndexNumber"),
                    "ParentIndexNumber": ep.get("ParentIndexNumber"),
                    "SeriesId": ep.get("SeriesId"),
                    "SeasonId": ep.get("SeasonId"),
                }
                for ep in items
                if ep.get("Id")
            ]
            party["episode_list_season_id"] = season_id

        # Capture both list position AND canonical IndexNumber. The list
        # position is informational (used for "Episode N of M" display);
        # IndexNumber is what binge-advance uses to find "next", because
        # the list can include specials at IndexNumber 0 (which would
        # mis-sort Ep1 to a non-zero position and make idx+1 jump past
        # the real next episode).
        result["index_number"] = details.get("IndexNumber")
        for idx, ep in enumerate(party["episode_list"]):
            if ep.get("Id") == item_id:
                result["episode_index"] = idx
                break

        next_ep = _find_next_episode(party["episode_list"], result["index_number"])
        if next_ep:
            result["next_item_id"] = next_ep.get("Id")
            result["next_item_title"] = next_ep.get("Name")

        # Debug-log the resolved metadata so users hitting weird auto-advance
        # behaviour can hand us a log line to diagnose. Includes the season's
        # IndexNumber distribution so we can spot specials / split-cour
        # numbering at a glance.
        list_numbers = [ep.get("IndexNumber") for ep in party["episode_list"]]
        logger.info(
            f"Binge ctx resolved: item={item_id} name={details.get('Name')!r} "
            f"IndexNumber={result['index_number']} "
            f"ParentIndexNumber={details.get('ParentIndexNumber')} "
            f"SeasonId={season_id} list_position={result['episode_index']} "
            f"season_index_numbers={list_numbers}"
        )

        return result

    def _default_audio_index(media_source):
        """Find the default audio track index from a media source."""
        if "MediaStreams" not in media_source:
            return None
        for stream in media_source["MediaStreams"]:
            if stream.get("Type") == "Audio" and stream.get("IsDefault"):
                return stream.get("Index")
        for stream in media_source["MediaStreams"]:
            if stream.get("Type") == "Audio":
                return stream.get("Index")
        return None

    def _create_user_stream(party, party_id, sid, item_id, media_source,
                            audio_index, subtitle_index, quality, start_seconds=0,
                            media_source_id=None):
        """Create a per-user Emby stream (own PlaySessionId and transcode).

        `media_source_id` selects between alternate versions when the
        item has multiple `MediaSources` (issue #43: theatrical /
        director's cut, mp4 / mkv, etc.). When None, Emby picks the
        default source (its `MediaSources[0]`) which matches the
        historical single-version behaviour.

        Returns the stream info dict, or None on failure.
        """
        access_token, user_id = _host_creds(party)
        start_ticks_for_info = int(start_seconds * 10_000_000) if start_seconds > 0 else 0
        # Normalise so a stale / unknown quality stored on the party can't
        # break stream creation; resolve to a max bitrate (None for Auto
        # and the resolution-only tiers -- get_playback_info treats None
        # as "no MaxStreamingBitrate" and lets Emby decide).
        normalised = normalise_quality_id(
            quality, force_transcode=bool(config.FORCE_TRANSCODE),
        )
        _, _, bitrate_kbps = resolve_quality(normalised)
        max_streaming_bitrate = bitrate_kbps * 1000 if bitrate_kbps else None
        playback_info = emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            media_source_id=media_source_id,
            max_streaming_bitrate=max_streaming_bitrate,
            start_time_ticks=start_ticks_for_info,
            access_token=access_token,
            user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            logger.error(f"Failed to get playback info for user stream (sid={sid})")
            return None

        user_media_source = playback_info["MediaSources"][0]
        media_source_id = user_media_source["Id"]
        play_session_id = playback_info.get("PlaySessionId")

        start_ticks = int(start_seconds * 10_000_000) if start_seconds > 0 else None

        from backend.src.stream_builder import StreamBuilder
        builder = StreamBuilder(emby_client, logger, config)
        stream_url_base = builder.build_stream_url(
            item_id=item_id,
            app_prefix=config.APP_PREFIX,
            media_source=user_media_source,
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            quality=normalised,
            start_time_ticks=start_ticks,
        )

        stream_info = {
            "play_session_id": play_session_id,
            "media_source_id": media_source_id,
            "stream_url_base": stream_url_base,
            "audio_index": audio_index,
            "subtitle_index": subtitle_index,
            "quality": normalised,
            "ready": False,
        }

        party.setdefault("user_streams", {})[sid] = stream_info

        run_time_seconds = party.get("current_video", {}).get("run_time_seconds")
        emby_client.report_playback_start(
            item_id=item_id, media_source_id=media_source_id,
            play_session_id=play_session_id, position_seconds=start_seconds,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=run_time_seconds,
            access_token=access_token,
            user_id=user_id,
        )

        logger.info(f"Created user stream for {party['users'].get(sid, sid)}: "
                     f"session={play_session_id}, start={start_seconds:.1f}s")
        return stream_info

    def _stop_user_stream(party, sid, position_seconds=0):
        """Stop a single user's Emby transcode and clean up."""
        user_streams = party.get("user_streams", {})
        stream = user_streams.pop(sid, None)
        if not stream or not stream.get("play_session_id"):
            return

        access_token, user_id = _host_creds(party)
        current_video = party.get("current_video")
        if current_video:
            emby_client.report_playback_stopped(
                item_id=current_video["item_id"],
                media_source_id=stream["media_source_id"],
                play_session_id=stream["play_session_id"],
                position_seconds=position_seconds,
                run_time_seconds=current_video.get("run_time_seconds"),
                access_token=access_token,
                user_id=user_id,
            )
        emby_client.stop_active_encodings(
            play_session_id=stream["play_session_id"],
            access_token=access_token,
        )

    def _stop_all_user_streams(party, position_seconds=0):
        """Stop all per-user transcodes."""
        for sid in list(party.get("user_streams", {}).keys()):
            _stop_user_stream(party, sid, position_seconds)

    def _wipe_host_if_orphan(party_id, party):
        """If host has already left and there's nothing left to play, wipe
        the stored token so the party fully transitions to LOCKED.
        """
        if party.get("host_left_at") is not None:
            party_manager.clear_host(party_id)
            logger.info(f"Party {party_id} -> LOCKED (host gone, playback ended)")

    def _start_ready_check(party, party_id):
        """Start a ready check for all users in the party."""
        expected = set(party["users"].keys())
        party["ready_check"] = {
            "active": True,
            "expected_sids": expected,
            "ready_sids": set(),
        }
        logger.debug(f"Ready check started for party {party_id}: expecting {len(expected)} users")

    async def _check_all_ready(party, party_id):
        """Check if all users are ready and emit all_ready if so."""
        rc = party.get("ready_check")
        if not rc or not rc.get("active"):
            return

        if rc["ready_sids"] >= rc["expected_sids"]:
            party["ready_check"] = None
            playback_state = party.get("playback_state", {})
            # Auto-play hand-off for binge-advance: when the previous
            # video ended into auto-advance, the user expectation is
            # "next episode just keeps playing" -- requiring the host
            # to click play after every episode defeats the whole
            # feature. The flag is set on the party when the watchdog
            # fires the restart and cleared here so a subsequent
            # manual select still pauses on ready as usual.
            auto_play_pending = party.pop("auto_play_after_ready", False)
            if auto_play_pending:
                playback_state["playing"] = True
            if playback_state.get("playing"):
                playback_state["last_update"] = datetime.now().isoformat()
            logger.info(f"All users ready in party {party_id}")
            await sio.emit("all_ready", {
                "time": playback_state.get("time", 0),
                "playing": playback_state.get("playing", False),
            }, room=party_id)
            if auto_play_pending:
                # Mirror the normal "host clicked play" broadcast so
                # every client's <video> resumes via the same code path
                # the seek/play handlers already use. Username is None
                # so the frontend doesn't render a "X resumed playback"
                # system message for an auto-event.
                await sio.emit("play", {
                    "time": playback_state.get("time", 0),
                    "username": None,
                    "auto_binge": True,
                }, room=party_id)
        else:
            ready_names = [party["users"].get(s, "?") for s in rc["ready_sids"]]
            waiting_names = [party["users"].get(s, "?") for s in rc["expected_sids"] - rc["ready_sids"]]
            await sio.emit("ready_check_update", {
                "ready": ready_names, "waiting": waiting_names,
            }, room=party_id)

    async def _restart_video_from_beginning(party, party_id, selector_client_id,
                                              item_id, item_name, item_overview,
                                              media_source_id=None):
        """Fetch fresh media info, stop existing streams, create per-user
        streams starting at 0, broadcast video_selected + ready_check.

        `selector_client_id` is stored as `current_video.selected_by` so
        the selector survives reloads / sid changes.

        `media_source_id` locks the playback to a specific Emby
        alternate version for the whole party (issue #43). When the
        selector picks from the library's version modal that id flows
        in here and gets stored on `current_video.media_source_id`;
        every subsequent stream operation (change_streams, late-join
        rejoin, vote-pass restart) reads it from there so the chosen
        version stays consistent across the playback. When None, Emby
        falls back to its default MediaSources[0], matching the
        single-version case.

        Returns True on success, False on failure (caller should emit error).
        """
        access_token, user_id = _host_creds(party)
        playback_info = emby_client.get_playback_info(
            item_id,
            media_source_id=media_source_id,
            access_token=access_token, user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            return False

        media_source = playback_info["MediaSources"][0]
        # When the caller didn't lock a version, capture whatever Emby
        # returned as the default so subsequent ops can refer to it
        # consistently (otherwise the late-join rejoin path would
        # silently re-default if Emby ever flips its default ordering).
        resolved_media_source_id = media_source.get("Id") or media_source_id
        default_audio = _default_audio_index(media_source)
        run_time_ticks = media_source.get("RunTimeTicks", 0)
        run_time_seconds = run_time_ticks / 10_000_000 if run_time_ticks else None

        # Stop all previous user streams
        prev_time = party["playback_state"].get("time", 0)
        _stop_all_user_streams(party, prev_time)

        # Resolve episode metadata (Type / SeriesId / SeasonId / IndexNumber)
        # for binge-watching. For Episode-typed items this also primes
        # the season's episode list cache so video_ended can decide
        # what "next" is without an extra Emby round-trip when the
        # episode finishes. Non-Episode items clear the cache.
        episode_ctx = _resolve_episode_context(party, item_id, access_token, user_id)

        # Store shared video info (no per-user fields). selected_by is the
        # persistent client_id, not the current sid.
        party["current_video"] = {
            "item_id": item_id, "title": item_name, "overview": item_overview,
            "run_time_seconds": run_time_seconds,
            "media_source_id": resolved_media_source_id,
            "selected_by": selector_client_id,
            "item_type": episode_ctx["item_type"],
            "series_id": episode_ctx["series_id"],
            "season_id": episode_ctx["season_id"],
            "episode_index": episode_ctx["episode_index"],
            "index_number": episode_ctx["index_number"],
            "next_item_id": episode_ctx["next_item_id"],
            "next_item_title": episode_ctx["next_item_title"],
        }

        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }

        # Start a ready check so clients show the waiting overlay until
        # every user has loaded their stream
        _start_ready_check(party, party_id)
        waiting_names = [party["users"].get(s, "?") for s in party["ready_check"]["expected_sids"]]

        # Create per-user streams and emit individually
        for user_sid in list(party["users"].keys()):
            stream = _create_user_stream(
                party, party_id, user_sid, item_id, media_source,
                audio_index=default_audio, subtitle_index=None,
                quality=DEFAULT_QUALITY_ID, start_seconds=0,
                media_source_id=resolved_media_source_id,
            )
            if not stream:
                continue

            stream_url = stream["stream_url_base"]
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = token_manager.get_or_create(party_id, user_sid)
                if user_token:
                    stream_url += f"&token={user_token}"

            await sio.emit("video_selected", {
                "video": {
                    "item_id": item_id, "title": item_name, "overview": item_overview,
                    "stream_url": stream_url,
                    "audio_index": default_audio, "subtitle_index": None,
                    "media_source_id": stream["media_source_id"],
                    "selected_by": selector_client_id, "quality": DEFAULT_QUALITY_ID,
                    "item_type": episode_ctx["item_type"],
                    "series_id": episode_ctx["series_id"],
                    "season_id": episode_ctx["season_id"],
                    "episode_index": episode_ctx["episode_index"],
                    "episode_count": len(party.get("episode_list") or []) if episode_ctx["item_type"] == "Episode" else 0,
                    "next_item_id": episode_ctx["next_item_id"],
                    "next_item_title": episode_ctx["next_item_title"],
                }
            }, to=user_sid)

        # Tell everyone the ready check is in progress
        await sio.emit("ready_check_update", {
            "ready": [], "waiting": waiting_names,
        }, room=party_id)

        return True

    # Expose the restart helper so party.py can reuse it for vote-pass restarts
    ctx['restart_video_from_beginning'] = _restart_video_from_beginning
    ctx['create_user_stream'] = _create_user_stream

    @sio.on("select_video")
    async def handle_select_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        item_id = data.get("item_id")
        item_name = data.get("item_name", "Unknown")
        item_overview = data.get("item_overview", "")
        # Optional alternate-version picker output from the library
        # modal. None for single-version items (or when the selector
        # didn't pick); the helper falls back to Emby's default source.
        media_source_id = data.get("media_source_id")

        if not party_manager.exists(party_id):
            await sio.emit("error", {"message": "Watch party not found"}, to=sid)
            return

        party = party_manager.get(party_id)

        # Party must be UNLOCKED. PLAYING-ONLY does not allow new picks
        # because the host is gone and a new transcode can not be started.
        if not party_manager.is_unlocked(party_id):
            await sio.emit(
                "error",
                {"message": "Party has no host -- login to become host first"},
                to=sid,
            )
            return

        selector_client_id = _client_id_for_sid(party, sid)
        if not selector_client_id:
            await sio.emit("error", {"message": "Not a party member"}, to=sid)
            return

        # A manual selection overrides any pending auto-advance. Silent
        # cancel: the upcoming video_selected broadcast is the
        # authoritative signal, so a stale "auto_advance_cancelled"
        # would just race the new modal off-screen. Also drop the
        # "auto-play after ready" flag so a manual pick from the
        # library doesn't unexpectedly start playing without the
        # selector having to hit play.
        await _cancel_pending_auto_advance(party_id, party, silent=True)
        party.pop("auto_play_after_ready", None)

        success = await _restart_video_from_beginning(
            party, party_id, selector_client_id, item_id, item_name, item_overview,
            media_source_id=media_source_id,
        )
        if not success:
            await sio.emit("error", {"message": "Failed to load video"}, to=sid)
            return

    @sio.on("stop_video")
    async def handle_stop_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)

        if not party or not party.get("current_video"):
            return

        caller_client_id = _client_id_for_sid(party, sid)
        if party["current_video"].get("selected_by") != caller_client_id:
            await sio.emit("error", {"message": "Only the selector can stop the video"}, to=sid)
            return

        video_title = party["current_video"].get("title", "Unknown")
        username = party["users"].get(sid, "Unknown")
        current_time = party["playback_state"].get("time", 0)

        _stop_all_user_streams(party, current_time)

        # Pending auto-advance can't apply to a stopped video; tear it
        # down. Loud cancel so any modal currently up snaps closed.
        await _cancel_pending_auto_advance(party_id, party, by_username=username)

        party["current_video"] = None
        party["ready_check"] = None
        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }

        # PLAYING-ONLY -> LOCKED transition if the host was gone.
        _wipe_host_if_orphan(party_id, party)

        await sio.emit("video_stopped", {
            "message": f"{username} stopped the video", "stopped_by": username,
        }, room=party_id)
        logger.info(f"User {username} stopped '{video_title}' in party {party_id}")

    @sio.on("change_streams")
    async def handle_change_streams(sid, data):
        """Per-user stream change (audio / subtitle / quality).

        Silent swap of the requesting user's stream. Other users keep
        playing normally; no party-wide pause, no ready check.

        The alternate Emby version (issue #43) is fixed party-wide at
        select_video time and stored on `current_video.media_source_id`,
        so audio / subtitle / quality changes always re-use that
        version automatically. Callers do not pass `media_source_id`
        here.
        """
        party_id = data.get("party_id", "").strip().upper()
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")
        quality = data.get("quality")

        party = party_manager.get(party_id)
        if not party or not party.get("current_video"):
            return

        # Need a usable host token. Allowed in both UNLOCKED and
        # PLAYING-ONLY because the in-flight video already has a session
        # under the stored token -- we just need it for the new transcode.
        if not party_manager.has_host_token(party_id):
            await sio.emit(
                "error",
                {"message": "Party token has expired"},
                to=sid,
            )
            return

        current_video = party["current_video"]
        item_id = current_video["item_id"]
        # The version was locked at select_video time. Pull from the
        # party's current_video so every per-user stream stays on the
        # same Emby source for the whole playback.
        media_source_id = current_video.get("media_source_id")
        access_token, user_id = _host_creds(party)

        # Resolve / sanitise the requested quality. A client can send the
        # `Auto` sentinel, a curated `<resolution>-<kbps>` id, or
        # legacy preset strings carried over from older party state.
        # When the input is missing, unknown, or `Auto` while
        # FORCE_TRANSCODE is on (Auto is incompatible with always-
        # transcode), fall back to either the previously-running stream
        # or the safe default.
        force_transcode = bool(config.FORCE_TRANSCODE)
        candidate = quality or party.get("user_streams", {}).get(sid, {}).get("quality")
        quality = normalise_quality_id(candidate, force_transcode=force_transcode)

        # Snapshot the party clock using the same elapsed-time projection
        # the sync handlers use.
        ps = party["playback_state"]
        was_playing = ps.get("playing", False)
        snapshot_time = ps.get("time", 0)
        if was_playing and ps.get("last_update"):
            try:
                last_update = datetime.fromisoformat(ps["last_update"])
                elapsed = (datetime.now() - last_update).total_seconds()
                if 0 < elapsed < 30:
                    snapshot_time += elapsed
            except Exception:
                pass

        # Stop this user's old transcode. Party clock keeps running.
        _stop_user_stream(party, sid, snapshot_time)

        _, _, bitrate_kbps = resolve_quality(quality)
        max_streaming_bitrate = bitrate_kbps * 1000 if bitrate_kbps else None
        playback_info = emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            media_source_id=media_source_id,
            max_streaming_bitrate=max_streaming_bitrate,
            start_time_ticks=int(snapshot_time * 10_000_000) if snapshot_time > 0 else 0,
            access_token=access_token,
            user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            return

        media_source = playback_info["MediaSources"][0]

        # Recompute the current party time after the Emby round-trip.
        current_time = ps.get("time", 0)
        if was_playing and ps.get("last_update"):
            try:
                last_update = datetime.fromisoformat(ps["last_update"])
                elapsed = (datetime.now() - last_update).total_seconds()
                if 0 < elapsed < 30:
                    current_time += elapsed
            except Exception:
                pass

        stream = _create_user_stream(
            party, party_id, sid, item_id, media_source,
            audio_index=audio_index, subtitle_index=subtitle_index,
            quality=quality, start_seconds=current_time,
            media_source_id=media_source_id,
        )
        if not stream:
            return

        stream_url = stream["stream_url_base"]
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = token_manager.get_or_create(party_id, sid)
            if user_token:
                stream_url += f"&token={user_token}"

        await sio.emit("streams_changed", {
            "video": {
                "item_id": item_id, "title": current_video["title"],
                "overview": current_video["overview"], "stream_url": stream_url,
                "audio_index": audio_index, "subtitle_index": subtitle_index,
                "media_source_id": stream["media_source_id"],
                "selected_by": current_video.get("selected_by"), "quality": quality,
            },
            "current_time": current_time,
            "was_playing": was_playing,
        }, to=sid)

        username = party["users"].get(sid, "Unknown")
        logger.info(
            f"Stream changed for {username}: audio={audio_index}, "
            f"sub={subtitle_index}, quality={quality}, resume_at={current_time:.1f}s"
        )

    @sio.on("video_ended")
    async def handle_video_ended(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        logger.info(f"Video ended in party {party_id}")
        final_pos = party.get("current_video", {}).get("run_time_seconds", 0)
        prev_video = party.get("current_video") or {}
        _stop_all_user_streams(party, final_pos)

        party["playback_state"] = {
            "playing": False, "time": 0, "last_update": datetime.now().isoformat(),
        }
        party["ready_check"] = None

        # If host already left, this is the moment we fully lock the party.
        # Do this BEFORE the binge-advance check; auto-advance can't start
        # if the host token is gone (the next _restart_video_from_beginning
        # would fail at get_playback_info anyway, but skipping early
        # avoids the failed Emby call + the broadcast that promised one).
        _wipe_host_if_orphan(party_id, party)

        await sio.emit("video_ended", {
            "party_id": party_id, "timestamp": datetime.now().isoformat(),
        }, room=party_id)

        # Binge-watching: if conditions are met, queue an auto-advance.
        # Branches off the just-ended video's stored episode metadata,
        # not anything from the payload, so a client can't spoof what
        # plays next.
        await _maybe_start_auto_advance(party_id, party, prev_video)

    async def _maybe_start_auto_advance(party_id, party, prev_video):
        """Inspect the just-ended video + party state and either kick off
        the auto-advance countdown or emit a 'no advance' signal (for
        end-of-season / not-an-episode / disabled) so the frontend can
        do the right thing (open the library, drop a system message).

        "Next" is the episode with the smallest IndexNumber strictly
        greater than the current one -- NOT just the next item in the
        list. Emby returns specials, theme songs, and extras alongside
        regular episodes in a season's child collection; sorting by
        ParentIndexNumber,IndexNumber still leaves IndexNumber=0
        specials at the top, which means the real Ep1 sits at list
        position 5+ instead of 0. Resolving by IndexNumber sidesteps
        that whole class of ordering quirks and gracefully handles
        gaps (missing Ep6 in a season -> next is Ep7).
        """
        # Admin master switch + per-party host opt-in.
        if not config.BINGE_WATCH_ENABLED or not party.get("binge_watch_active"):
            return
        if not party_manager.is_unlocked(party_id):
            return
        if prev_video.get("item_type") != "Episode":
            return

        episode_list = party.get("episode_list") or []
        current_idx_number = prev_video.get("index_number")
        if current_idx_number is None or not episode_list:
            return

        # Find next: smallest IndexNumber strictly greater than current.
        # Skips specials (IndexNumber 0 / None) and survives gaps.
        next_episode = None
        for ep in episode_list:
            ep_num = ep.get("IndexNumber")
            if ep_num is None or ep_num <= current_idx_number:
                continue
            if next_episode is None or ep_num < next_episode.get("IndexNumber"):
                next_episode = ep

        # End of season: nothing past the current IndexNumber. Tell the
        # frontend so it can pop the library and drop a "season
        # finished" system message.
        if next_episode is None:
            await sio.emit("binge_finished", {
                "series_id": prev_video.get("series_id"),
                "season_id": prev_video.get("season_id"),
            }, room=party_id)
            return

        # Selector still in the party? If they've left we don't have
        # anyone to anchor the advance against, so skip silently. The
        # host (if still around) can pick the next episode manually.
        selector_client_id = prev_video.get("selected_by")
        if not _selector_still_present(party, selector_client_id):
            return

        await _queue_auto_advance(party_id, party, prev_video, next_episode)

    def _selector_still_present(party, selector_client_id):
        if not selector_client_id:
            return False
        return selector_client_id in (party.get("sid_client_ids") or {}).values()

    async def _queue_auto_advance(party_id, party, prev_video, next_episode):
        """Set the pending auto-advance state, emit auto_advance_pending,
        and start the watchdog that fires _restart_video_from_beginning
        when the countdown expires."""
        # Cancel any prior pending advance defensively. video_ended
        # shouldn't fire while one's already queued, but if a client
        # bugs out and re-emits, don't pile up watchdog tasks.
        await _cancel_pending_auto_advance(party_id, party, by_username=None, silent=True)

        countdown = max(1, int(config.BINGE_WATCH_COUNTDOWN_SECONDS))
        deadline = datetime.now() + timedelta(seconds=countdown)
        next_item_id = next_episode.get("Id")
        next_title = next_episode.get("Name") or "Next episode"
        # Display label uses the next episode's canonical IndexNumber
        # (Emby's "this is Episode N") rather than its list position.
        # Total is the highest IndexNumber in the season -- not the
        # list length, which would include any specials Emby returns.
        next_index_number = next_episode.get("IndexNumber")
        total_episodes = max(
            (ep.get("IndexNumber") or 0) for ep in (party.get("episode_list") or [])
        ) if party.get("episode_list") else 0

        task = asyncio.create_task(_auto_advance_watchdog(party_id, countdown))
        party["pending_auto_advance"] = {
            "next_item_id": next_item_id,
            "next_title": next_title,
            "next_index_number": next_index_number,
            "selector_client_id": prev_video.get("selected_by"),
            "deadline": deadline.isoformat(),
            "task": task,
        }
        await sio.emit("auto_advance_pending", {
            "next_item_id": next_item_id,
            "next_title": next_title,
            "next_index_number": next_index_number,
            "total_episodes": total_episodes,
            "deadline": deadline.isoformat(),
            "countdown_seconds": countdown,
        }, room=party_id)
        logger.info(
            f"Auto-advance queued in party {party_id}: "
            f"next={next_item_id} ({next_title}) in {countdown}s"
        )

    async def _auto_advance_watchdog(party_id, countdown):
        """Sleep countdown seconds; if the pending advance is still set,
        kick off the restart. Cancelled by _cancel_pending_auto_advance
        if the user clicks cancel or the admin flips the toggle off."""
        try:
            await asyncio.sleep(countdown)
        except asyncio.CancelledError:
            return

        party = party_manager.get(party_id)
        if not party:
            return
        pending = party.get("pending_auto_advance")
        if not pending:
            return

        # Re-check the gates -- the host may have left or the admin may
        # have flipped the toggle off in the interval.
        if not config.BINGE_WATCH_ENABLED or not party.get("binge_watch_active"):
            await _cancel_pending_auto_advance(party_id, party, by_username=None)
            return
        if not party_manager.is_unlocked(party_id):
            await _cancel_pending_auto_advance(party_id, party, by_username=None)
            return

        next_item_id = pending["next_item_id"]
        next_title = pending["next_title"]
        selector_client_id = pending["selector_client_id"]
        party["pending_auto_advance"] = None

        await sio.emit("auto_advance_fired", {
            "next_item_id": next_item_id,
            "next_title": next_title,
        }, room=party_id)

        # Tell _check_all_ready that the next video should kick into
        # play as soon as everyone's transcode has loaded. Without this
        # the host would have to click play after every episode -- not
        # what anyone expects from "binge mode". Set BEFORE the
        # restart so the new ready-check phase sees it.
        party["auto_play_after_ready"] = True

        success = await _restart_video_from_beginning(
            party, party_id, selector_client_id, next_item_id, next_title, "",
        )
        if not success:
            logger.warning(
                f"Auto-advance failed to start next episode in party {party_id}: "
                f"{next_item_id}"
            )
            await sio.emit("error", {
                "message": "Failed to auto-advance to next episode"
            }, room=party_id)

    async def _cancel_pending_auto_advance(party_id, party, by_username=None, silent=False):
        """Cancel any queued auto-advance and (unless silent) notify the
        room. silent=True is used when we replace one pending advance
        with another -- the new auto_advance_pending event is the
        authoritative signal and an intermediate 'cancelled' would just
        confuse the UI."""
        pending = party.get("pending_auto_advance")
        if not pending:
            return False
        task = pending.get("task")
        if task and not task.done():
            task.cancel()
        party["pending_auto_advance"] = None
        if not silent:
            await sio.emit("auto_advance_cancelled", {
                "by_username": by_username,
            }, room=party_id)
            logger.info(
                f"Auto-advance cancelled in party {party_id} "
                f"(by={by_username or 'system'})"
            )
        return True

    # Expose cancel helper so the admin-config and host-leave paths can
    # tear down a pending auto-advance from outside this module.
    ctx['cancel_pending_auto_advance'] = _cancel_pending_auto_advance

    @sio.on("auto_advance_cancel")
    async def handle_auto_advance_cancel(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return
        username = party["users"].get(sid)
        await _cancel_pending_auto_advance(party_id, party, by_username=username)

    @sio.on("set_binge_watch_active")
    async def handle_set_binge_watch_active(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        active = bool(data.get("active"))
        party = party_manager.get(party_id)
        if not party:
            return

        # Host-only: only the user holding the host token can toggle the
        # session-level switch. Non-hosts get nothing; we don't even
        # send back an error because the button shouldn't have been
        # visible to them in the first place.
        caller_client_id = _client_id_for_sid(party, sid)
        if not caller_client_id or party.get("host_client_id") != caller_client_id:
            return
        if not config.BINGE_WATCH_ENABLED:
            # Admin toggle is off -- feature isn't available. Silently
            # refuse and re-broadcast state so a stale client UI snaps
            # back to reality.
            await sio.emit("binge_watch_state_changed", {
                "available": False, "active": False,
            }, room=party_id)
            return

        party["binge_watch_active"] = active
        # Turning it off mid-countdown should kill the queued advance.
        if not active:
            await _cancel_pending_auto_advance(party_id, party, by_username=None)
        await sio.emit("binge_watch_state_changed", {
            "available": True, "active": active,
        }, room=party_id)
        logger.info(
            f"Binge-watch {'enabled' if active else 'disabled'} in party {party_id} "
            f"by {party['users'].get(sid, '?')}"
        )

    @sio.on("report_progress")
    async def handle_report_progress(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        party = party_manager.get(party_id)
        if not party or not party.get("current_video"):
            return

        user_stream = party.get("user_streams", {}).get(sid)
        if not user_stream or not user_stream.get("play_session_id"):
            return

        # Only the selector updates the authoritative party clock.
        # Match by persistent client_id so a reload preserves the role.
        current_video = party["current_video"]
        caller_client_id = _client_id_for_sid(party, sid)
        if current_video.get("selected_by") == caller_client_id:
            party["playback_state"]["time"] = current_time
            party["playback_state"]["last_update"] = datetime.now().isoformat()

        is_playing = party["playback_state"].get("playing", False)
        access_token, user_id = _host_creds(party)
        emby_client.report_playback_progress(
            item_id=current_video["item_id"],
            media_source_id=user_stream["media_source_id"],
            play_session_id=user_stream["play_session_id"],
            position_seconds=current_time, is_paused=not is_playing, event_name="TimeUpdate",
            audio_index=user_stream.get("audio_index"),
            subtitle_index=user_stream.get("subtitle_index") if user_stream.get("subtitle_index") != -1 else None,
            run_time_seconds=current_video.get("run_time_seconds"),
            access_token=access_token,
            user_id=user_id,
        )

    @sio.on("stream_ready")
    async def handle_stream_ready(sid, data):
        """Client signals their HLS stream is loaded and ready to play."""
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        user_stream = party.get("user_streams", {}).get(sid)
        if user_stream:
            user_stream["ready"] = True

        rc = party.get("ready_check")
        if rc and rc.get("active"):
            rc["ready_sids"].add(sid)
            username = party["users"].get(sid, "Unknown")
            logger.debug(f"{username} stream ready in party {party_id}")
            await _check_all_ready(party, party_id)
