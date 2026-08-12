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
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from backend.src.domain import (
    AutoAdvance,
    EpisodeRef,
    PlaybackState,
    SelectedMedia,
    UserStream,
)
from backend.src.quality import (
    DEFAULT_QUALITY_ID,
    normalise_quality_id,
    resolve_quality,
)


class EpisodeContext(TypedDict):
    item_type: str | None
    series_id: str | None
    season_id: str | None
    episode_index: int | None
    index_number: int | None
    next_item_id: str | None
    next_item_title: str | None


# Never start at the very last frame: Emby answers a start at or past the end
# with a zero-length manifest, which the player reports as an immediate `ended`.
END_OF_MEDIA_BUFFER_SECONDS = 5.0


def media_source_run_time(media_source: dict | None) -> float:
    """Runtime of an Emby media source in seconds, 0.0 when it does not say."""
    if not isinstance(media_source, dict):
        return 0.0
    return (media_source.get("RunTimeTicks") or 0) / 10_000_000


def clamp_start_seconds(start_seconds: float | None, run_time: float | None) -> float:
    """Hold a resume offset inside the runtime of the source being started.

    One definition shared by every path that resumes playback. It existed in
    two places and was missing from a third: the in-player version switch,
    which is the one route that can change WHICH source is playing, and so the
    one most able to hand Emby a start time past the end of media.
    """
    clamped = max(0.0, float(start_seconds or 0))
    if run_time:
        clamped = min(clamped, max(0.0, float(run_time) - END_OF_MEDIA_BUFFER_SECONDS))
    return clamped


def register(ctx):
    sio = ctx["sio"]
    emby_client = ctx["emby_client"]
    config = ctx["config"]
    logger = ctx["logger"]
    party_manager = ctx["party_manager"]
    token_manager = ctx["token_manager"]
    rate_limiter = ctx.get("rate_limiter")

    def _client_id_for_sid(party, sid):
        """Look up the persistent client_id mapped to this socket sid."""
        return party.sid_client_ids.get(sid)

    def _host_creds(party):
        """Return (access_token, user_id) for the party's current host."""
        return party.host_access_token, party.host_user_id

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
            ep_num = ep.index_number
            if ep_num is None or ep_num <= current_index_number:
                continue
            if next_ep is None or ep_num < next_ep.index_number:
                next_ep = ep
        return next_ep

    async def _resolve_episode_context(party, item_id, access_token, user_id):
        """Look up Type / SeriesId / SeasonId / IndexNumber for the
        currently-selected item and (for Episodes) cache the season's
        full episode list on the party so video_ended can find "next"
        without re-querying Emby. Returns a dict with keys item_type,
        series_id, season_id, episode_index -- all may be None for
        non-Episode items or when Emby fails to return metadata.

        Episode list caching keys on season_id; switching to a different
        season's episode (or to a non-Episode item) clears the cache.
        """
        result: EpisodeContext = {
            "item_type": None,
            "series_id": None,
            "season_id": None,
            "episode_index": None,
            "index_number": None,
            # Precomputed "what plays after this" so the frontend NEXT
            # badge can render the moment binge is armed, not just
            # during the countdown window. None for movies, the last
            # episode in a season, or anything without IndexNumber.
            "next_item_id": None,
            "next_item_title": None,
        }
        episode_list = None
        episode_list_season_id = None
        if not user_id:
            return result, episode_list, episode_list_season_id

        details = await emby_client.get_item_details(
            item_id,
            access_token=access_token,
            user_id=user_id,
        )
        if not details:
            return result, episode_list, episode_list_season_id

        item_type = details.get("Type")
        result["item_type"] = item_type
        if item_type != "Episode":
            return result, episode_list, episode_list_season_id

        series_id = details.get("SeriesId")
        # Emby exposes the season as ParentId for episodes; SeasonId is
        # also set but ParentId is the field used elsewhere in this
        # codebase for the immediate parent.
        season_id = details.get("SeasonId") or details.get("ParentId")
        result["series_id"] = series_id
        result["season_id"] = season_id

        if not season_id:
            return result, episode_list, episode_list_season_id

        # Cache hit: same season as last selection, reuse the list.
        if party.episode_list_season_id == season_id and party.episode_list:
            episode_list = list(party.episode_list)
        else:
            episodes = await emby_client.get_season_episodes(
                season_id,
                access_token=access_token,
                user_id=user_id,
            )
            items = episodes.get("Items", []) if episodes else []
            # Trim to the fields binge-watching needs; we don't want to
            # store full Emby payloads on long-lived party state.
            episode_list = [
                EpisodeRef(
                    item_id=ep["Id"],
                    name=ep.get("Name") or "",
                    index_number=ep.get("IndexNumber"),
                    parent_index_number=ep.get("ParentIndexNumber"),
                    series_id=ep.get("SeriesId"),
                    season_id=ep.get("SeasonId"),
                )
                for ep in items
                if ep.get("Id")
            ]
        episode_list_season_id = season_id

        # Capture both list position AND canonical IndexNumber. The list
        # position is informational (used for "Episode N of M" display);
        # IndexNumber is what binge-advance uses to find "next", because
        # the list can include specials at IndexNumber 0 (which would
        # mis-sort Ep1 to a non-zero position and make idx+1 jump past
        # the real next episode).
        result["index_number"] = details.get("IndexNumber")
        for idx, ep in enumerate(episode_list):
            if ep.item_id == item_id:
                result["episode_index"] = idx
                break

        next_ep = _find_next_episode(episode_list, result["index_number"])
        if next_ep:
            result["next_item_id"] = next_ep.item_id
            result["next_item_title"] = next_ep.name

        # Debug-log the resolved metadata so users hitting weird auto-advance
        # behaviour can hand us a log line to diagnose. Includes the season's
        # IndexNumber distribution so we can spot specials / split-cour
        # numbering at a glance.
        list_numbers = [ep.index_number for ep in episode_list]
        logger.info(
            f"Binge ctx resolved: item={item_id} name={details.get('Name')!r} "
            f"IndexNumber={result['index_number']} "
            f"ParentIndexNumber={details.get('ParentIndexNumber')} "
            f"SeasonId={season_id} list_position={result['episode_index']} "
            f"season_index_numbers={list_numbers}"
        )

        return result, episode_list, episode_list_season_id

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

    async def _create_user_stream(
        party,
        party_id,
        sid,
        item_id,
        _media_source,
        audio_index,
        subtitle_index,
        quality,
        start_seconds=0,
        media_source_id=None,
    ):
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
            quality,
            force_transcode=bool(config.FORCE_TRANSCODE),
        )
        _, _, bitrate_kbps = resolve_quality(normalised)
        max_streaming_bitrate = bitrate_kbps * 1000 if bitrate_kbps else None
        playback_info = await emby_client.get_playback_info(
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

        # Per-viewer codec capability. Streams are already per viewer, so
        # two people in the same party can legitimately get different
        # codecs: the one whose browser decodes HEVC keeps it, the one
        # whose browser does not gets h264 (#61). Absent means the client
        # never reported, which build_params treats as h264-only.
        client_id = _client_id_for_sid(party, sid)
        client_codecs = party.client_codecs.get(client_id) if client_id else None

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
            client_codecs=client_codecs,
        )

        stream_info = UserStream(
            play_session_id=play_session_id,
            media_source_id=media_source_id,
            stream_url_base=stream_url_base,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            quality=normalised,
            start_offset=start_seconds,
        )

        if not await party_manager.commit_user_stream(party_id, sid, stream_info):
            await emby_client.stop_active_encodings(
                play_session_id=play_session_id,
                access_token=access_token,
            )
            return None

        run_time_seconds = party.current_video.run_time_seconds
        await emby_client.report_playback_start(
            item_id=item_id,
            media_source_id=media_source_id,
            play_session_id=play_session_id,
            position_seconds=start_seconds,
            audio_index=audio_index,
            subtitle_index=subtitle_index if subtitle_index != -1 else None,
            run_time_seconds=run_time_seconds,
            access_token=access_token,
            user_id=user_id,
        )

        logger.info(
            f"Created user stream for {party.username_for_sid(sid, sid)}: "
            f"session={play_session_id}, start={start_seconds:.1f}s"
        )
        return stream_info

    async def _stop_user_stream(party, sid, position_seconds=0):
        """Stop a single user's Emby transcode and clean up."""
        user_streams = party.user_streams
        stream = user_streams.pop(sid, None)
        if not stream or not stream.play_session_id:
            return

        access_token, user_id = _host_creds(party)
        current_video = party.current_video
        if current_video:
            await emby_client.report_playback_stopped(
                item_id=current_video.item_id,
                media_source_id=stream.media_source_id,
                play_session_id=stream.play_session_id,
                position_seconds=position_seconds,
                run_time_seconds=current_video.run_time_seconds,
                access_token=access_token,
                user_id=user_id,
            )
        await emby_client.stop_active_encodings(
            play_session_id=stream.play_session_id,
            access_token=access_token,
        )

    async def _stop_all_user_streams(party, position_seconds=0):
        """Stop all per-user transcodes."""
        for sid in list(party.user_streams.keys()):
            await _stop_user_stream(party, sid, position_seconds)

    def _wipe_host_if_orphan(party_id, party):
        """If host has already left and there's nothing left to play, wipe
        the stored token so the party fully transitions to LOCKED.
        """
        if party.host_left_at is not None:
            party_manager.clear_host(party_id)
            logger.info(f"Party {party_id} -> LOCKED (host gone, playback ended)")

    async def _check_all_ready(_party, party_id):
        """Check if all users are ready and emit all_ready if so."""
        commit = await party_manager.settle_ready_check(party_id)
        if commit is None:
            return

        if commit.complete:
            logger.info(f"All users ready in party {party_id}")
            await sio.emit(
                "all_ready",
                {
                    "time": commit.playback_time,
                    "playing": commit.playback_playing,
                },
                room=party_id,
            )
            if commit.auto_play:
                # Mirror the normal "host clicked play" broadcast so
                # every client's <video> resumes via the same code path
                # the seek/play handlers already use. Username is None
                # so the frontend doesn't render a "X resumed playback"
                # system message for an auto-event.
                await sio.emit(
                    "play",
                    {
                        "time": commit.playback_time,
                        "username": None,
                        "auto_binge": True,
                    },
                    room=party_id,
                )
        else:
            await sio.emit(
                "ready_check_update",
                {
                    "ready": list(commit.ready_names),
                    "waiting": list(commit.waiting_names),
                },
                room=party_id,
            )

    async def _restart_video_from_beginning(
        party,
        party_id,
        selector_client_id,
        item_id,
        item_name,
        item_overview,
        media_source_id=None,
        start_seconds=0,
        audio_index=None,
        subtitle_index=None,
        quality=None,
        reservation=None,
    ):
        """Fetch fresh media info, stop existing streams, create per-user
        streams starting at `start_seconds`, broadcast video_selected +
        ready_check.

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

        `start_seconds` is the resume offset for the whole party. 0
        (default) starts from the beginning -- matches binge auto-
        advance, vote-pass restart, and library picks of fresh items.
        Non-zero comes from the host accepting a "Resume at HH:MM:SS"
        prompt; the value is the Emby UserData.PlaybackPositionTicks
        converted to seconds. Clamped below to the runtime so a stale
        cached resume position can't push the start past the end of
        the file.

        Returns True on success, False on failure (caller should emit error).
        """
        if reservation is None:
            reservation = await party_manager.reserve_operation(party_id, "select_video")
            if reservation is None:
                return False
        access_token, user_id = _host_creds(party)
        playback_info = await emby_client.get_playback_info(
            item_id,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            media_source_id=media_source_id,
            access_token=access_token,
            user_id=user_id,
        )
        if not playback_info or "MediaSources" not in playback_info:
            return False

        if reservation is not None and not await party_manager.reservation_is_current(
            party_id, "select_video", reservation
        ):
            play_session_id = playback_info.get("PlaySessionId")
            if play_session_id:
                await emby_client.stop_active_encodings(
                    play_session_id=play_session_id,
                    access_token=access_token,
                )
            logger.info(
                "Discarded stale select reservation for party %s; transcode cleanup=%s",
                party_id,
                bool(play_session_id),
            )
            return False

        media_source = playback_info["MediaSources"][0]
        # When the caller didn't lock a version, capture whatever Emby
        # returned as the default so subsequent ops can refer to it
        # consistently (otherwise the late-join rejoin path would
        # silently re-default if Emby ever flips its default ordering).
        resolved_media_source_id = media_source.get("Id") or media_source_id
        selected_audio = (
            audio_index if audio_index is not None else _default_audio_index(media_source)
        )
        selected_quality = normalise_quality_id(
            quality or DEFAULT_QUALITY_ID,
            force_transcode=bool(config.FORCE_TRANSCODE),
        )
        run_time_ticks = media_source.get("RunTimeTicks", 0)
        run_time_seconds = run_time_ticks / 10_000_000 if run_time_ticks else None

        # Stop all previous user streams
        prev_time = party.playback_state.time
        await _stop_all_user_streams(party, prev_time)

        # Resolve episode metadata (Type / SeriesId / SeasonId / IndexNumber)
        # for binge-watching. For Episode-typed items this also primes
        # the season's episode list cache so video_ended can decide
        # what "next" is without an extra Emby round-trip when the
        # episode finishes. Non-Episode items clear the cache.
        episode_ctx, episode_list, episode_list_season_id = await _resolve_episode_context(
            party, item_id, access_token, user_id
        )

        # Build shared video info (no per-user fields). selected_by is the
        # persistent client_id, not the current sid.
        video = SelectedMedia(
            item_id=item_id,
            title=item_name,
            overview=item_overview,
            run_time_seconds=run_time_seconds,
            media_source_id=resolved_media_source_id,
            selected_by=selector_client_id,
            item_type=episode_ctx["item_type"],
            series_id=episode_ctx["series_id"],
            season_id=episode_ctx["season_id"],
            episode_index=episode_ctx["episode_index"],
            index_number=episode_ctx["index_number"],
            next_item_id=episode_ctx["next_item_id"],
            next_item_title=episode_ctx["next_item_title"],
        )

        # Clamp the requested resume offset to a safe window inside the runtime
        # so a stale UserData.PlaybackPositionTicks (e.g. from a media
        # re-encode that shortened the file) can't push past the end of media
        # or back below zero.
        resume_offset = clamp_start_seconds(start_seconds, run_time_seconds)

        committed_party = await party_manager.commit_video_selection(
            party_id,
            reservation,
            video=video,
            playback_state=PlaybackState(time=resume_offset),
            episode_list=episode_list,
            episode_list_season_id=episode_list_season_id,
        )
        if committed_party is None:
            play_session_id = playback_info.get("PlaySessionId")
            if play_session_id:
                await emby_client.stop_active_encodings(
                    play_session_id=play_session_id,
                    access_token=access_token,
                )
            logger.info("Discarded stale video metadata commit for %s", party_id)
            return False
        party = committed_party

        # The manager started a ready check in the same atomic commit.
        waiting_names = [party.username_for_sid(s, "?") for s in party.ready_check.expected_sids]

        # Create per-user streams and emit individually. When a user's
        # stream fails to build (Emby playback_info transient error,
        # MediaSources missing, etc.) we MUST drop that sid from
        # expected_sids or the ready-check hangs forever: the sid never
        # receives video_selected, so it never emits stream_ready, so
        # ready_sids >= expected_sids is unreachable. Frontend has a
        # 15s safety timeout that dismisses the overlay, but the party
        # is still in a broken state (ready_check dict never cleared,
        # auto_play_after_ready never consumed) unless we cleanup here.
        for user_sid in party.sids():
            stream = await _create_user_stream(
                party,
                party_id,
                user_sid,
                item_id,
                media_source,
                audio_index=selected_audio,
                subtitle_index=subtitle_index,
                quality=selected_quality,
                start_seconds=resume_offset,
                media_source_id=resolved_media_source_id,
            )
            if not stream:
                logger.warning(
                    f"_create_user_stream failed for sid={user_sid} in {party_id}; "
                    f"dropping from ready_check.expected_sids to prevent deadlock"
                )
                rc = party.ready_check
                if rc:
                    await party_manager.drop_ready_member(party_id, user_sid)
                # Notify the failed client so they don't stare at a
                # blank player waiting for a video_selected that will
                # never come.
                await sio.emit(
                    "error",
                    {
                        "message": "Could not start your stream. Ask the host to re-select the video.",
                    },
                    to=user_sid,
                )
                continue

            stream_url = stream.stream_url_base
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                user_token = token_manager.get_or_create(party_id, user_sid)
                if user_token:
                    stream_url += f"&token={user_token}"

            await sio.emit(
                "video_selected",
                {
                    "video": {
                        "item_id": item_id,
                        "title": item_name,
                        "overview": item_overview,
                        "stream_url": stream_url,
                        "audio_index": stream.audio_index,
                        "subtitle_index": stream.subtitle_index,
                        "media_source_id": stream.media_source_id,
                        "selected_by": selector_client_id,
                        "quality": stream.quality,
                        "item_type": episode_ctx["item_type"],
                        "series_id": episode_ctx["series_id"],
                        "season_id": episode_ctx["season_id"],
                        "episode_index": episode_ctx["episode_index"],
                        "episode_count": len(party.episode_list or [])
                        if episode_ctx["item_type"] == "Episode"
                        else 0,
                        "next_item_id": episode_ctx["next_item_id"],
                        "next_item_title": episode_ctx["next_item_title"],
                    }
                },
                to=user_sid,
            )

        # Tell everyone the ready check is in progress.
        # Recompute waiting_names from the LIVE expected_sids because
        # some may have been discarded due to stream-creation failures
        # above; otherwise the overlay lists ghosts nobody is waiting on.
        rc = party.ready_check
        live_expected = rc.expected_sids if rc else set()
        waiting_names = [party.username_for_sid(s, "?") for s in live_expected]
        await sio.emit(
            "ready_check_update",
            {
                "ready": [],
                "waiting": waiting_names,
            },
            room=party_id,
        )

        # Edge case: every user's stream failed. expected_sids is now
        # empty, so the natural stream_ready path would never fire
        # _check_all_ready. Run it once here to complete the check and
        # consume auto_play_after_ready cleanly.
        if not live_expected:
            await _check_all_ready(party, party_id)

        return True

    # Expose the restart helper so party.py can reuse it for vote-pass restarts
    ctx["restart_video_from_beginning"] = _restart_video_from_beginning
    ctx["create_user_stream"] = _create_user_stream

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
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")
        quality = data.get("quality")
        resume_mode = data.get("resume_mode", "start_over")
        binge = data.get("binge")
        # Optional resume position in seconds. The frontend reads
        # UserData.PlaybackPositionTicks from the library response and
        # offers the host a Resume / Start-over choice when it's > 0
        # and Played is false. 0 (the default) starts from the
        # beginning, matching pre-resume behavior. Sanity-clamped to
        # [0, run_time) below once we know the runtime.
        try:
            start_seconds = float(data.get("start_seconds") or 0)
        except (TypeError, ValueError):
            start_seconds = 0.0
        if start_seconds < 0:
            start_seconds = 0.0
        if resume_mode == "start_over":
            start_seconds = 0.0

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
        await party_manager.set_auto_play_after_ready(party_id, False)

        reservation = await party_manager.reserve_operation(party_id, "select_video")
        if reservation is None:
            return
        try:
            success = await _restart_video_from_beginning(
                party,
                party_id,
                selector_client_id,
                item_id,
                item_name,
                item_overview,
                media_source_id=media_source_id,
                start_seconds=start_seconds,
                audio_index=audio_index,
                subtitle_index=subtitle_index,
                quality=quality,
                reservation=reservation,
            )
        finally:
            await party_manager.release_operation(party_id, "select_video", reservation)
        if not success:
            await sio.emit("error", {"message": "Failed to load video"}, to=sid)
            return
        if binge is not None and party.host_client_id == selector_client_id:
            active = bool(binge) and bool(config.BINGE_WATCH_ENABLED)
            await party_manager.set_binge_watch(party_id, active)
            await sio.emit(
                "binge_watch_state_changed",
                {"available": bool(config.BINGE_WATCH_ENABLED), "active": active},
                room=party_id,
            )

    @sio.on("stop_video")
    async def handle_stop_video(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)

        if not party or not party.current_video:
            return

        caller_client_id = _client_id_for_sid(party, sid)
        if party.current_video.selected_by != caller_client_id:
            await sio.emit("error", {"message": "Only the selector can stop the video"}, to=sid)
            return

        video_title = party.current_video.title
        username = party.username_for_sid(sid)
        current_time = party.playback_state.time

        await _stop_all_user_streams(party, current_time)

        # Pending auto-advance can't apply to a stopped video; tear it
        # down. Loud cancel so any modal currently up snaps closed.
        await _cancel_pending_auto_advance(party_id, party, by_username=username)

        await party_manager.clear_video_state(party_id)

        # PLAYING-ONLY -> LOCKED transition if the host was gone.
        _wipe_host_if_orphan(party_id, party)

        await sio.emit(
            "video_stopped",
            {
                "message": f"{username} stopped the video",
                "stopped_by": username,
            },
            room=party_id,
        )
        logger.info(f"User {username} stopped '{video_title}' in party {party_id}")

    @sio.on("change_streams")
    async def handle_change_streams(sid, data):
        """Per-user stream change (version / audio / subtitle / quality).

        Silent swap of the requesting user's stream. Other users keep
        playing normally; no party-wide pause, no ready check.

        The selected version defaults to the party selection, but callers
        may choose another source for their own stream during playback.
        """
        party_id = data.get("party_id", "").strip().upper()
        audio_index = data.get("audio_index")
        subtitle_index = data.get("subtitle_index")
        quality = data.get("quality")
        requested_media_source_id = data.get("media_source_id")

        party = party_manager.get(party_id)
        if not party or not party.current_video:
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

        current_video = party.current_video
        item_id = current_video.item_id
        # The version was locked at select_video time. Pull from the
        # party's current_video so every per-user stream stays on the
        # same Emby source for the whole playback.
        media_source_id = requested_media_source_id or current_video.media_source_id
        access_token, user_id = _host_creds(party)

        # Resolve / sanitise the requested quality. A client can send the
        # `Auto` sentinel, a curated `<resolution>-<kbps>` id, or
        # legacy preset strings carried over from older party state.
        # When the input is missing, unknown, or `Auto` while
        # FORCE_TRANSCODE is on (Auto is incompatible with always-
        # transcode), fall back to either the previously-running stream
        # or the safe default.
        force_transcode = bool(config.FORCE_TRANSCODE)
        existing_stream = party.user_streams.get(sid)
        candidate = quality or (existing_stream.quality if existing_stream else None)
        quality = normalise_quality_id(candidate, force_transcode=force_transcode)

        # Snapshot the party clock using the same elapsed-time projection
        # the sync handlers use.
        ps = party.playback_state
        was_playing = ps.playing
        snapshot_time = ps.time
        if was_playing and ps.last_update:
            try:
                last_update = datetime.fromisoformat(ps.last_update)
                elapsed = (datetime.now(UTC) - last_update).total_seconds()
                if 0 < elapsed < 30:
                    snapshot_time += elapsed
            except (TypeError, ValueError):
                pass

        # Stop this user's old transcode. Party clock keeps running.
        await _stop_user_stream(party, sid, snapshot_time)

        _, _, bitrate_kbps = resolve_quality(quality)
        max_streaming_bitrate = bitrate_kbps * 1000 if bitrate_kbps else None
        playback_info = await emby_client.get_playback_info(
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
        current_time = ps.time
        if was_playing and ps.last_update:
            try:
                last_update = datetime.fromisoformat(ps.last_update)
                elapsed = (datetime.now(UTC) - last_update).total_seconds()
                if 0 < elapsed < 30:
                    current_time += elapsed
            except (TypeError, ValueError):
                pass

        # Clamped against the source we are switching TO, not the one the party
        # clock was measured against. This route honours a caller-supplied
        # media_source_id, so switching a 150-minute extended cut to a
        # 120-minute theatrical at 02:20:00 asked Emby to start past the end of
        # media. The runtime is already in hand from the fetch above.
        start_seconds = clamp_start_seconds(current_time, media_source_run_time(media_source))

        stream = await _create_user_stream(
            party,
            party_id,
            sid,
            item_id,
            media_source,
            audio_index=audio_index,
            subtitle_index=subtitle_index,
            quality=quality,
            start_seconds=start_seconds,
            media_source_id=media_source_id,
        )
        if not stream:
            return

        stream_url = stream.stream_url_base
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = token_manager.get_or_create(party_id, sid)
            if user_token:
                stream_url += f"&token={user_token}"

        await sio.emit(
            "streams_changed",
            {
                "video": {
                    "item_id": item_id,
                    "title": current_video.title,
                    "overview": current_video.overview,
                    "stream_url": stream_url,
                    "audio_index": audio_index,
                    "subtitle_index": subtitle_index,
                    "media_source_id": stream.media_source_id,
                    "selected_by": current_video.selected_by,
                    "quality": quality,
                },
                "current_time": current_time,
                "was_playing": was_playing,
            },
            to=sid,
        )

        username = party.username_for_sid(sid)
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

        # Caller-identity gate. Previously any client (or a browser
        # extension / racing HLS.js end-of-stream double-fire) could
        # emit video_ended and unconditionally stop every user's
        # transcode + reset playback_state + trigger LOCKED-state
        # transition via _wipe_host_if_orphan. Only the selector may
        # signal end-of-video; if there is no selector on record we
        # fall back to the host so vote-pass / binge-fired states still
        # work.
        caller_client_id = party.sid_client_ids.get(sid)
        current_video = party.current_video
        if current_video is None:
            return
        selected_by = current_video.selected_by
        host_client_id = party.host_client_id
        allowed = (selected_by and caller_client_id == selected_by) or (
            not selected_by and host_client_id and caller_client_id == host_client_id
        )
        if not allowed:
            logger.info(
                f"handle_video_ended REJECTED: sid={sid} "
                f"client_id={caller_client_id} is not selector/host of {party_id}"
            )
            return

        # Idempotency: current_video is cleared at the end of this
        # handler, so a duplicate emit re-enters with prev_video empty
        # and skips the destructive path. Previously duplicate emits
        # (HLS.js ENDED twice, retry loops) would silently re-arm
        # _queue_auto_advance and reset the countdown from full.
        logger.info(f"Video ended in party {party_id}")
        final_pos = current_video.run_time_seconds or 0
        prev_video = current_video
        await _stop_all_user_streams(party, final_pos)

        # Clear current_video BEFORE the auto-advance check so a
        # duplicate video_ended emit bails at the idempotency guard
        # above. _maybe_start_auto_advance still has prev_video in its
        # closure so binge lookup still works.
        await party_manager.clear_video_state(party_id)

        # If host already left, this is the moment we fully lock the party.
        # Do this BEFORE the binge-advance check; auto-advance can't start
        # if the host token is gone (the next _restart_video_from_beginning
        # would fail at get_playback_info anyway, but skipping early
        # avoids the failed Emby call + the broadcast that promised one).
        _wipe_host_if_orphan(party_id, party)

        await sio.emit(
            "video_ended",
            {
                "party_id": party_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            room=party_id,
        )

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
        if not config.BINGE_WATCH_ENABLED or not party.binge_watch_active:
            return
        if not party_manager.is_unlocked(party_id):
            return
        if prev_video.item_type != "Episode":
            return

        episode_list = party.episode_list or []
        current_idx_number = prev_video.index_number
        if current_idx_number is None or not episode_list:
            # Can't compute "next episode" without an IndexNumber (rare;
            # happens on freshly-added episodes before Emby's metadata
            # fetch completes) or without a cached season list. Emit
            # binge_finished so the frontend opens the library and drops
            # the "pick another" system message instead of leaving the
            # player stuck on the just-ended episode.
            await sio.emit(
                "binge_finished",
                {
                    "reason": "no_index" if current_idx_number is None else "no_episode_list",
                },
                room=party_id,
            )
            return

        # Find next: smallest IndexNumber strictly greater than current.
        # Skips specials (IndexNumber 0 / None) and survives gaps.
        next_episode = None
        for ep in episode_list:
            ep_num = ep.index_number
            if ep_num is None or ep_num <= current_idx_number:
                continue
            if next_episode is None or ep_num < next_episode.index_number:
                next_episode = ep

        # End of season: nothing past the current IndexNumber. Tell the
        # frontend so it can pop the library and drop a "season
        # finished" system message.
        if next_episode is None:
            await sio.emit(
                "binge_finished",
                {
                    "series_id": prev_video.series_id,
                    "season_id": prev_video.season_id,
                },
                room=party_id,
            )
            return

        # Selector still in the party? If they've left we don't have
        # anyone to anchor the advance against, so skip silently. The
        # host (if still around) can pick the next episode manually.
        selector_client_id = prev_video.selected_by
        if not _selector_still_present(party, selector_client_id):
            return

        await _queue_auto_advance(party_id, party, prev_video, next_episode)

    def _selector_still_present(party, selector_client_id):
        if not selector_client_id:
            return False
        return selector_client_id in (party.sid_client_ids or {}).values()

    async def _queue_auto_advance(party_id, party, prev_video, next_episode):
        """Set the pending auto-advance state, emit auto_advance_pending,
        and start the watchdog that fires _restart_video_from_beginning
        when the countdown expires."""
        # Cancel any prior pending advance defensively. video_ended
        # shouldn't fire while one's already queued, but if a client
        # bugs out and re-emits, don't pile up watchdog tasks.
        await _cancel_pending_auto_advance(party_id, party, by_username=None, silent=True)

        countdown = max(1, int(config.BINGE_WATCH_COUNTDOWN_SECONDS))
        deadline = datetime.now(UTC) + timedelta(seconds=countdown)
        next_item_id = next_episode.item_id
        next_title = next_episode.name or "Next episode"
        # Display label uses the next episode's canonical IndexNumber
        # (Emby's "this is Episode N") rather than its list position.
        # Total is the highest IndexNumber in the season -- not the
        # list length, which would include any specials Emby returns.
        next_index_number = next_episode.index_number
        total_episodes = (
            max((ep.index_number or 0) for ep in (party.episode_list or []))
            if party.episode_list
            else 0
        )

        task = asyncio.create_task(_auto_advance_watchdog(party_id, countdown))
        pending = AutoAdvance(
            next_item_id=next_item_id,
            next_title=next_title,
            next_index_number=next_index_number,
            selector_client_id=prev_video.selected_by,
            deadline=deadline.isoformat(),
            task=task,
        )
        if not await party_manager.queue_auto_advance(party_id, pending):
            task.cancel()
            return
        await sio.emit(
            "auto_advance_pending",
            {
                "next_item_id": next_item_id,
                "next_title": next_title,
                "next_index_number": next_index_number,
                "total_episodes": total_episodes,
                "deadline": deadline.isoformat(),
                "countdown_seconds": countdown,
            },
            room=party_id,
        )
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
        pending = party.pending_auto_advance
        if not pending:
            return

        # Re-check the gates -- the host may have left or the admin may
        # have flipped the toggle off in the interval.
        if not config.BINGE_WATCH_ENABLED or not party.binge_watch_active:
            await _cancel_pending_auto_advance(party_id, party, by_username=None)
            return
        if not party_manager.is_unlocked(party_id):
            await _cancel_pending_auto_advance(party_id, party, by_username=None)
            return

        pending = await party_manager.take_auto_advance(party_id)
        if pending is None:
            return
        next_item_id = pending.next_item_id
        next_title = pending.next_title
        selector_client_id = pending.selector_client_id

        await sio.emit(
            "auto_advance_fired",
            {
                "next_item_id": next_item_id,
                "next_title": next_title,
            },
            room=party_id,
        )

        # Tell _check_all_ready that the next video should kick into
        # play as soon as everyone's transcode has loaded. Without this
        # the host would have to click play after every episode -- not
        # what anyone expects from "binge mode". Set BEFORE the
        # restart so the new ready-check phase sees it.
        await party_manager.set_auto_play_after_ready(party_id, True)

        success = await _restart_video_from_beginning(
            party,
            party_id,
            selector_client_id,
            next_item_id,
            next_title,
            "",
        )
        if not success:
            # Restart failed -- clear the flag we optimistically set
            # above so a later restart (via vote-pass, or a manual
            # select-then-play) doesn't inherit it and auto-play a
            # different video without the host clicking play.
            await party_manager.set_auto_play_after_ready(party_id, False)
            logger.warning(
                f"Auto-advance failed to start next episode in party {party_id}: {next_item_id}"
            )
            await sio.emit(
                "error", {"message": "Failed to auto-advance to next episode"}, room=party_id
            )

    async def _cancel_pending_auto_advance(party_id, _party, by_username=None, silent=False):
        """Cancel any queued auto-advance and (unless silent) notify the
        room. silent=True is used when we replace one pending advance
        with another -- the new auto_advance_pending event is the
        authoritative signal and an intermediate 'cancelled' would just
        confuse the UI."""
        pending = await party_manager.take_auto_advance(party_id)
        if not pending:
            return False
        task = pending.task
        if task and not task.done():
            task.cancel()
        if not silent:
            await sio.emit(
                "auto_advance_cancelled",
                {
                    "by_username": by_username,
                },
                room=party_id,
            )
            logger.info(
                f"Auto-advance cancelled in party {party_id} (by={by_username or 'system'})"
            )
        return True

    # Expose cancel helper so the admin-config and host-leave paths can
    # tear down a pending auto-advance from outside this module.
    ctx["cancel_pending_auto_advance"] = _cancel_pending_auto_advance

    @sio.on("auto_advance_cancel")
    async def handle_auto_advance_cancel(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return
        username = party.username_for_sid(sid, "") or None
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
        if not caller_client_id or party.host_client_id != caller_client_id:
            return
        if not config.BINGE_WATCH_ENABLED:
            # Admin toggle is off -- feature isn't available. Silently
            # refuse and re-broadcast state so a stale client UI snaps
            # back to reality.
            await sio.emit(
                "binge_watch_state_changed",
                {
                    "available": False,
                    "active": False,
                },
                room=party_id,
            )
            return

        await party_manager.set_binge_watch(party_id, active)
        # Turning it off mid-countdown should kill the queued advance.
        if not active:
            await _cancel_pending_auto_advance(party_id, party, by_username=None)
        await sio.emit(
            "binge_watch_state_changed",
            {
                "available": True,
                "active": active,
            },
            room=party_id,
        )
        logger.info(
            f"Binge-watch {'enabled' if active else 'disabled'} in party {party_id} "
            f"by {party.username_for_sid(sid, '?')}"
        )

    @sio.on("set_party_hidden")
    async def handle_set_party_hidden(sid, data):
        """Keep this party off the public index listing.

        Unlisted rather than private: anyone holding the code can still join,
        exactly as before. The listing is a convenience for finding an open
        room, and a host running a private evening should not have to choose
        between being advertised and being reachable.
        """
        party_id = data.get("party_id", "").strip().upper()
        hidden = bool(data.get("hidden"))
        party = party_manager.get(party_id)
        if not party:
            return

        # Host-only, same rule as the binge switch above: the control is not
        # rendered for anyone else, so a request from a non-host is a client
        # that should not have sent it and gets no reply.
        caller_client_id = _client_id_for_sid(party, sid)
        if not caller_client_id or party.host_client_id != caller_client_id:
            return

        await party_manager.set_hidden(party_id, hidden)
        # Broadcast to the room, not just the caller: the host may have the
        # party open in more than one tab, and a stale switch there would
        # misreport whether the party is advertised.
        await sio.emit("party_visibility_changed", {"hidden": hidden}, room=party_id)
        logger.info(
            f"Party {party_id} {'hidden from' if hidden else 'listed in'} the index "
            f"by {party.username_for_sid(sid, '?')}"
        )

    # report_progress throttle. The handler fires a synchronous outbound
    # Emby HTTP call on every emit; previously there was no cap, so a
    # joined member could 1000-Hz spam and (a) pin the asyncio event
    # loop via the sync requests.post and (b) hammer Emby with one
    # POST per emit under the host's access_token. Cap to one report
    # per sid every 4 seconds (frontend fires at ~5s cadence in normal
    # operation, so this only clips abuse).
    report_progress_min_interval = 4.0

    @sio.on("report_progress")
    async def handle_report_progress(sid, data):
        party_id = data.get("party_id", "").strip().upper()
        current_time = data.get("time", 0)
        commit = await party_manager.commit_progress(party_id, sid, current_time)
        if commit is None:
            return

        # Throttle Emby-facing reports per sid.
        if rate_limiter is not None:
            decision = rate_limiter.check(
                f"progress:{sid}",
                limit=1,
                window_seconds=int(report_progress_min_interval),
            )
            if not decision.allowed:
                return

        await emby_client.report_playback_progress(
            item_id=commit.video.item_id,
            media_source_id=commit.stream.media_source_id,
            play_session_id=commit.stream.play_session_id,
            position_seconds=current_time,
            is_paused=not commit.playing,
            event_name="TimeUpdate",
            audio_index=commit.stream.audio_index,
            subtitle_index=(
                commit.stream.subtitle_index if commit.stream.subtitle_index != -1 else None
            ),
            run_time_seconds=commit.video.run_time_seconds,
            access_token=commit.host_access_token,
            user_id=commit.host_user_id,
        )

    @sio.on("stream_ready")
    async def handle_stream_ready(sid, data):
        """Client signals their HLS stream is loaded and ready to play."""
        party_id = data.get("party_id", "").strip().upper()
        party = party_manager.get(party_id)
        if not party:
            return

        username = await party_manager.mark_stream_ready(party_id, sid)
        if username is not None:
            logger.debug(f"{username} stream ready in party {party_id}")
            await _check_all_ready(party, party_id)
