"""Owns typed watch-party aggregates and their transition locks."""

import asyncio
import logging
import secrets
import time
from dataclasses import replace
from datetime import datetime
from typing import Dict, Optional

from backend.src.config import Config
from backend.src.domain import (
    AutoAdvance,
    EpisodeRef,
    Party,
    DepartureCommit,
    JoinVote,
    Participant,
    PlaybackControlCommit,
    PlaybackReportSnapshot,
    PlaybackState,
    ReadyCheck,
    ReadyCommit,
    SelectedMedia,
    UserStream,
)
from backend.src.utils import generate_party_code


# =============================================================================
# Party Manager
# =============================================================================

class PartyManager:
    """Manages all watch parties and their state transitions."""

    def __init__(self, config: Config, logger: logging.Logger):
        self.watch_parties: Dict[str, Party] = {}
        self._party_locks: dict[str, asyncio.Lock] = {}
        self._config = config
        self._logger = logger
        # Tracks the static party's id as last known to this manager, so
        # sync_static_party() can detect when STATIC_SESSION_ID changes
        # and clean up the old party.
        self._last_static_id: Optional[str] = None

        # Create static party on startup if configured
        if config.STATIC_SESSION_ENABLED:
            pid = config.STATIC_SESSION_ID.upper()
            self._create_party_dict(party_id=pid)
            self._last_static_id = pid
            self._logger.info(f"Static session mode: {pid}")

    @property
    def static_party_id(self) -> Optional[str]:
        if self._config.STATIC_SESSION_ENABLED:
            return self._config.STATIC_SESSION_ID.upper()
        return None

    def _new_party_dict(self, party_id: str) -> Party:
        """Create a party aggregate."""
        return Party.create(party_id)

    def _create_party_dict(self, party_id: str) -> Party:
        """Create and store a party aggregate."""
        party = self._new_party_dict(party_id)
        self.watch_parties[party_id] = party
        self._party_locks[party_id] = party.lock
        return party

    def lock_for(self, party_id: str) -> asyncio.Lock:
        return self._party_locks.setdefault(party_id, asyncio.Lock())

    async def pop_if_empty(self, party_id: str) -> Optional[Party]:
        if party_id == self.static_party_id:
            return None
        lock = self.lock_for(party_id)
        async with lock:
            party = self.watch_parties.get(party_id)
            if not party or party.member_count:
                return None
            party.closing = True
            party.generation = int(party.generation) + 1
            party.operation_reservations.clear()
            removed = self.watch_parties.pop(party_id)
        self._party_locks.pop(party_id, None)
        return removed

    async def pop_party(self, party_id: str) -> Optional[Party]:
        lock = self.lock_for(party_id)
        async with lock:
            removed = self.watch_parties.get(party_id)
            if removed is not None:
                removed.closing = True
                removed.generation += 1
                removed.operation_reservations.clear()
                self.watch_parties.pop(party_id, None)
        self._party_locks.pop(party_id, None)
        return removed

    async def reserve_operation(self, party_id: str, kind: str) -> tuple[int, str] | None:
        """Reserve a network-dependent operation without holding its party lock."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if not party or party.closing:
                return None
            token = secrets.token_urlsafe(18)
            generation = int(party.generation)
            party.operation_reservations[kind] = token
            return generation, token

    async def reservation_is_current(
        self,
        party_id: str,
        kind: str,
        reservation: tuple[int, str],
    ) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if not party or party.closing:
                return False
            generation, token = reservation
            return (
                int(party.generation) == generation
                and party.operation_reservations.get(kind) == token
            )

    async def release_operation(
        self,
        party_id: str,
        kind: str,
        reservation: tuple[int, str],
    ) -> None:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return
        async with lock:
            party = self.watch_parties.get(party_id)
            if not party:
                return
            _, token = reservation
            reservations = party.operation_reservations
            if reservations.get(kind) == token:
                reservations.pop(kind, None)

    @staticmethod
    def _playback_report_snapshot(party: Party, sid: str) -> PlaybackReportSnapshot:
        stream = party.user_streams.get(sid)
        return PlaybackReportSnapshot(
            current_video=party.current_video,
            user_stream=replace(stream) if stream else None,
            host_access_token=party.host_access_token,
            host_user_id=party.host_user_id,
        )

    async def commit_playback_control(
        self,
        party_id: str,
        sid: str,
        *,
        playing: bool,
        position: float,
    ) -> PlaybackControlCommit | None:
        """Validate membership and atomically commit play/pause state."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return None
            client_id = party.sid_client_ids.get(sid)
            if client_id is None:
                return None
            party.playback_state = PlaybackState(playing=playing, time=position)
            return PlaybackControlCommit(
                client_id=client_id,
                username=party.username_for_sid(sid, "Someone"),
                report=self._playback_report_snapshot(party, sid),
            )

    async def commit_seek(
        self,
        party_id: str,
        sid: str,
        *,
        position: float,
        was_playing: bool,
    ) -> PlaybackControlCommit | None:
        """Atomically validate and commit a seek plus optional ready check."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return None
            client_id = party.sid_client_ids.get(sid)
            if client_id is None:
                return None
            ready_check = party.ready_check
            if ready_check and ready_check.active:
                return None
            party.playback_state = PlaybackState(
                playing=was_playing,
                time=position,
            )
            waiting_names: tuple[str, ...] = ()
            if was_playing:
                expected = set(party.sids())
                party.ready_check = ReadyCheck(expected_sids=expected)
                waiting_names = tuple(
                    party.username_for_sid(member, "?") for member in expected
                )
            return PlaybackControlCommit(
                client_id=client_id,
                username=party.username_for_sid(sid, "Someone"),
                report=self._playback_report_snapshot(party, sid),
                waiting_names=waiting_names,
            )

    async def commit_video_selection(
        self,
        party_id: str,
        reservation: tuple[int, str],
        *,
        video: SelectedMedia,
        playback_state: PlaybackState,
        episode_list: list[EpisodeRef] | None,
        episode_list_season_id: str | None,
    ) -> Party | None:
        """Install network-derived selection state iff its reservation is current."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return None
            generation, token = reservation
            if (
                party.generation != generation
                or party.operation_reservations.get("select_video") != token
            ):
                return None
            party.current_video = video
            party.playback_state = playback_state
            party.episode_list = episode_list
            party.episode_list_season_id = episode_list_season_id
            party.ready_check = ReadyCheck(expected_sids=set(party.sids()))
            return party

    async def commit_user_stream(
        self,
        party_id: str,
        sid: str,
        stream: UserStream,
    ) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing or not party.has_sid(sid):
                return False
            party.user_streams[sid] = stream
            return True

    async def depart_socket(
        self,
        party_id: str,
        sid: str,
        *,
        forget_participant: bool,
    ) -> DepartureCommit | None:
        """Atomically detach one socket and settle its ready-check membership."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return None
            stream = party.user_streams.pop(sid, None)
            client_id = party.sid_client_ids.pop(sid, None)
            participant = party.participants.get(client_id) if client_id else None
            username = participant.username if participant else None
            party.join_times.pop(sid, None)
            party.drift_strikes.pop(sid, None)
            if forget_participant and client_id:
                party.participants.pop(client_id, None)

            all_ready = False
            auto_play = False
            ready_names: tuple[str, ...] = ()
            waiting_names: tuple[str, ...] = ()
            ready_check = party.ready_check
            if ready_check and ready_check.active:
                ready_check.expected_sids.discard(sid)
                ready_check.ready_sids.discard(sid)
                if (
                    ready_check.expected_sids
                    and ready_check.ready_sids >= ready_check.expected_sids
                ):
                    all_ready = True
                    party.ready_check = None
                    auto_play = party.auto_play_after_ready
                    party.auto_play_after_ready = False
                    if auto_play:
                        party.playback_state.playing = True
                    if party.playback_state.playing:
                        party.playback_state.last_update = datetime.now().isoformat()
                elif not ready_check.expected_sids:
                    party.ready_check = None
                    party.auto_play_after_ready = False
                else:
                    ready_names = tuple(
                        party.username_for_sid(member, "?")
                        for member in ready_check.ready_sids
                    )
                    waiting_names = tuple(
                        party.username_for_sid(member, "?")
                        for member in ready_check.expected_sids
                        - ready_check.ready_sids
                    )
            return DepartureCommit(
                username=username,
                client_id=client_id,
                stream=stream,
                all_ready=all_ready,
                auto_play=auto_play,
                playback_time=party.playback_state.time,
                playback_playing=party.playback_state.playing,
                ready_names=ready_names,
                waiting_names=waiting_names,
                current_video=party.current_video,
                host_access_token=party.host_access_token,
                host_user_id=party.host_user_id,
            )

    async def replace_socket(
        self,
        party_id: str,
        *,
        old_sid: str | None,
        new_sid: str,
        username: str,
        client_id: str | None,
        avatar_uuid: str | None,
    ) -> DepartureCommit | None:
        """Atomically migrate a participant identity to a replacement socket."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return None
            old_stream = None
            if old_sid and old_sid != new_sid:
                party.join_times.pop(old_sid, None)
                party.sid_client_ids.pop(old_sid, None)
                drift_strikes = party.drift_strikes.pop(old_sid, None)
                if drift_strikes is not None:
                    party.drift_strikes[new_sid] = drift_strikes
                old_stream = party.user_streams.pop(old_sid, None)
                ready_check = party.ready_check
                if ready_check and ready_check.active:
                    if old_sid in ready_check.expected_sids:
                        ready_check.expected_sids.discard(old_sid)
                        ready_check.expected_sids.add(new_sid)
                    if old_sid in ready_check.ready_sids:
                        ready_check.ready_sids.discard(old_sid)
                        ready_check.ready_sids.add(new_sid)

            party.join_times[new_sid] = datetime.now().isoformat()
            if client_id:
                existing = party.participants.get(client_id)
                party.participants[client_id] = Participant(
                    client_id=client_id,
                    username=username,
                    sid=new_sid,
                    avatar_uuid=avatar_uuid
                    or (existing.avatar_uuid if existing else None),
                )
                party.sid_client_ids[new_sid] = client_id
            return DepartureCommit(
                username=username,
                client_id=client_id,
                stream=old_stream,
                all_ready=False,
                auto_play=False,
                playback_time=party.playback_state.time,
                playback_playing=party.playback_state.playing,
                ready_names=(),
                waiting_names=(),
                current_video=party.current_video,
                host_access_token=party.host_access_token,
                host_user_id=party.host_user_id,
            )

    async def restore_host_presence(self, party_id: str) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return False
            party.host_left_at = None
            return True

    async def begin_join_vote(self, party_id: str, vote: JoinVote) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing or party.pending_join is not None:
                return False
            party.pending_join = vote
            return True

    async def refresh_join_applicant(
        self,
        party_id: str,
        *,
        client_id: str | None,
        sid: str,
    ) -> tuple[str, JoinVote] | None:
        """Move an idempotent pending applicant onto its current socket."""
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            vote = party.pending_join if party else None
            if vote is None or not client_id or vote.client_id != client_id:
                return None
            old_sid = vote.sid
            vote.sid = sid
            return old_sid, vote

    async def clear_join_vote(
        self,
        party_id: str,
        *,
        cooldown_seconds: float = 0,
    ) -> JoinVote | None:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None:
                return None
            vote = party.pending_join
            party.pending_join = None
            if cooldown_seconds > 0:
                party.join_cooldown_until = time.time() + cooldown_seconds
            return vote

    async def set_join_vote_task(
        self,
        party_id: str,
        task: asyncio.Task | None,
    ) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.pending_join is None:
                return False
            party.pending_join.timeout_task = task
            return True

    async def record_join_vote(
        self,
        party_id: str,
        sid: str,
        choice: str,
    ) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            vote = party.pending_join if party else None
            if vote is None or sid not in vote.eligible_voters:
                return False
            vote.votes[sid] = choice
            return True

    async def remove_join_voter(self, party_id: str, sid: str) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            vote = party.pending_join if party else None
            if vote is None or sid not in vote.eligible_voters:
                return False
            vote.eligible_voters.discard(sid)
            vote.votes.pop(sid, None)
            if vote.selector_sid == sid:
                vote.selector_sid = None
            return True

    async def drop_ready_member(self, party_id: str, sid: str) -> None:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return
        async with lock:
            party = self.watch_parties.get(party_id)
            if party and party.ready_check:
                party.ready_check.expected_sids.discard(sid)
                party.ready_check.ready_sids.discard(sid)

    async def mark_stream_ready(self, party_id: str, sid: str) -> str | None:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.ready_check is None:
                return None
            stream = party.user_streams.get(sid)
            if stream:
                stream.ready = True
            party.ready_check.ready_sids.add(sid)
            return party.username_for_sid(sid)

    async def settle_ready_check(self, party_id: str) -> ReadyCommit | None:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            ready = party.ready_check if party else None
            if party is None or ready is None or not ready.active:
                return None
            complete = ready.ready_sids >= ready.expected_sids
            auto_play = False
            ready_names: tuple[str, ...] = ()
            waiting_names: tuple[str, ...] = ()
            if complete:
                party.ready_check = None
                auto_play = party.auto_play_after_ready
                party.auto_play_after_ready = False
                if auto_play:
                    party.playback_state.playing = True
                if party.playback_state.playing:
                    party.playback_state.last_update = datetime.now().isoformat()
            else:
                ready_names = tuple(
                    party.username_for_sid(sid, "?") for sid in ready.ready_sids
                )
                waiting_names = tuple(
                    party.username_for_sid(sid, "?")
                    for sid in ready.expected_sids - ready.ready_sids
                )
            return ReadyCommit(
                complete=complete,
                auto_play=auto_play,
                playback_time=party.playback_state.time,
                playback_playing=party.playback_state.playing,
                ready_names=ready_names,
                waiting_names=waiting_names,
            )

    async def clear_video_state(self, party_id: str) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return False
            party.current_video = None
            party.ready_check = None
            party.playback_state = PlaybackState()
            party.auto_play_after_ready = False
            return True

    async def set_auto_play_after_ready(self, party_id: str, active: bool) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return False
            party.auto_play_after_ready = active
            return True

    async def queue_auto_advance(
        self,
        party_id: str,
        pending: AutoAdvance,
    ) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return False
            party.pending_auto_advance = pending
            return True

    async def take_auto_advance(self, party_id: str) -> AutoAdvance | None:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return None
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None:
                return None
            pending = party.pending_auto_advance
            party.pending_auto_advance = None
            return pending

    async def set_binge_watch(self, party_id: str, active: bool) -> bool:
        lock = self._party_locks.get(party_id)
        if lock is None:
            return False
        async with lock:
            party = self.watch_parties.get(party_id)
            if party is None or party.closing:
                return False
            party.binge_watch_active = active
            return True

    def create_party(self) -> str:
        """Create a new party with a generated ID. Returns party_id."""
        party_id = generate_party_code(self.watch_parties)
        self._create_party_dict(party_id)
        return party_id

    def get(self, party_id: str) -> Optional[Party]:
        """Get a party by ID, or None."""
        return self.watch_parties.get(party_id)

    def exists(self, party_id: str) -> bool:
        return party_id in self.watch_parties

    def get_all(self) -> Dict[str, Party]:
        """Get all active parties."""
        return self.watch_parties

    def ensure_static_party(self) -> Optional[str]:
        """Recreate the static party if it was deleted. Returns party_id or None."""
        if not self._config.STATIC_SESSION_ENABLED:
            return None
        pid = self._config.STATIC_SESSION_ID.upper()
        if pid not in self.watch_parties:
            self._create_party_dict(pid)
            self._logger.info(f"Recreated static party: {pid}")
        return pid

    def sync_static_party(self) -> tuple[Optional[str], Optional[str]]:
        """Reconcile the static party with the current runtime config.

        Called when STATIC_SESSION_ENABLED or STATIC_SESSION_ID changes
        via the admin panel so the change takes effect without a restart:

        - If the static id changed, remove the old party before creating
          the new one.
        - If the feature was disabled, remove the previously-created
          static party so it stops responding to joins.
        - If the feature is enabled and the configured party is missing,
          create it.

        Returns (new_static_id, dissolved_party_id). The dissolved id
        is non-None when this call deleted a party (caller can use it
        to kick sockets, revoke HLS tokens, broadcast dissolved event).
        """
        cfg_enabled = self._config.STATIC_SESSION_ENABLED
        cfg_id = self._config.STATIC_SESSION_ID.upper() if cfg_enabled else None

        dissolved: Optional[str] = None
        if self._last_static_id and self._last_static_id != cfg_id:
            old = self._last_static_id
            if old in self.watch_parties:
                dissolved = old
                self._logger.info(f"Reserved previous static party for dissolution: {old}")

        if cfg_id and cfg_id not in self.watch_parties:
            self._create_party_dict(cfg_id)
            self._logger.info(f"Created static party: {cfg_id}")

        self._last_static_id = cfg_id
        return cfg_id, dissolved

    def count(self) -> int:
        return len(self.watch_parties)

    # =========================================================================
    # Host management
    # =========================================================================

    def set_host(
        self,
        party_id: str,
        *,
        client_id: str,
        user_id: str,
        access_token: str,
        username: str,
        is_admin: bool = False,
    ) -> bool:
        """Mark a party member as host. Returns False if party is missing.

        Overwrites any prior host and clears host_left_at so the party
        moves to UNLOCKED.
        """
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        party.host_client_id = client_id
        party.host_user_id = user_id
        party.host_access_token = access_token
        party.host_username = username
        party.host_is_admin = bool(is_admin)
        party.host_left_at = None
        return True

    def clear_host(self, party_id: str) -> bool:
        """Wipe all host fields. Library and HLS are now both locked."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        party.host_client_id = None
        party.host_user_id = None
        party.host_access_token = None
        party.host_username = None
        party.host_is_admin = False
        party.host_left_at = None
        return True

    def mark_host_left(self, party_id: str) -> bool:
        """Stamp host_left_at without clearing the token.

        Transitions the party to PLAYING-ONLY (library locked, HLS still
        served on the stored token). A full clear happens later, either
        on grace expiry or on video_ended/stop_video.
        """
        party = self.watch_parties.get(party_id)
        if not party or not party.host_access_token:
            return False
        party.host_left_at = datetime.now().isoformat()
        return True

    def has_host_token(self, party_id: str) -> bool:
        """True iff an Emby access token is stored (HLS usable)."""
        party = self.watch_parties.get(party_id)
        return bool(party and party.host_access_token)

    def disable_binge_watch_globally(self) -> list[str]:
        """Tear down per-party binge state across every party. Used by
        the admin save path when BINGE_WATCH_ENABLED flips off, so any
        currently-active session loses its button + countdown
        immediately rather than waiting for the next page reload.

        Returns a list of party_ids that were affected (so the caller
        can broadcast binge_watch_state_changed only to rooms that
        actually had it on).
        """
        affected = []
        for party_id, party in self.watch_parties.items():
            was_active = bool(party.binge_watch_active)
            pending = party.pending_auto_advance
            if not was_active and not pending:
                continue
            if pending:
                task = pending.task
                if task and not task.done():
                    task.cancel()
                party.pending_auto_advance = None
            party.binge_watch_active = False
            affected.append(party_id)
        return affected

    def is_unlocked(self, party_id: str) -> bool:
        """True iff a host is present and the library is browsable."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        return bool(party.host_access_token) and party.host_left_at is None

    def is_playing_only(self, party_id: str) -> bool:
        """True iff host has left but HLS is still serving a current video."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        return (
            bool(party.host_access_token)
            and party.host_left_at is not None
            and party.current_video is not None
        )

    def get_host_token(self, party_id: str) -> Optional[str]:
        """Return the host's Emby access token, or None when fully locked."""
        party = self.watch_parties.get(party_id)
        if not party:
            return None
        return party.host_access_token

    def get_host_user_id(self, party_id: str) -> Optional[str]:
        """Return the host's Emby user id (used for Emby API calls)."""
        party = self.watch_parties.get(party_id)
        if not party:
            return None
        return party.host_user_id

    def members_list(self, party_id: str) -> list:
        """Return [{username, avatar_uuid}, ...] for everyone in the party.

        Derives connected members from canonical participant state.
        """
        party = self.watch_parties.get(party_id)
        if not party:
            return []
        out = []
        for sid, cid in party.sid_client_ids.items():
            p = party.participants.get(cid)
            out.append({
                "username": p.username if p else party.username_for_sid(sid),
                "avatar_uuid": p.avatar_uuid if p else None,
            })
        return out
