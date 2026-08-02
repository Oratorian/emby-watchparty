"""Owns typed watch-party aggregates and their transition locks."""

import asyncio
import logging
import secrets
from datetime import datetime
from typing import Dict, Optional

from backend.src.config import Config
from backend.src.domain import Party
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
            if not party or party.get("users"):
                return None
            party["closing"] = True
            party["generation"] = int(party.get("generation", 0)) + 1
            party.get("operation_reservations", {}).clear()
            removed = self.watch_parties.pop(party_id)
        self._party_locks.pop(party_id, None)
        return removed

    async def pop_party(self, party_id: str) -> Optional[Party]:
        lock = self.lock_for(party_id)
        async with lock:
            removed = self.watch_parties.get(party_id)
            if removed is not None:
                removed["closing"] = True
                removed["generation"] = int(removed.get("generation", 0)) + 1
                removed.get("operation_reservations", {}).clear()
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
            if not party or party.get("closing"):
                return None
            token = secrets.token_urlsafe(18)
            generation = int(party.get("generation", 0))
            party.setdefault("operation_reservations", {})[kind] = token
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
            if not party or party.get("closing"):
                return False
            generation, token = reservation
            return (
                int(party.get("generation", 0)) == generation
                and party.get("operation_reservations", {}).get(kind) == token
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
            reservations = party.get("operation_reservations", {})
            if reservations.get(kind) == token:
                reservations.pop(kind, None)

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

    def add_user(self, party_id: str, sid: str, username: str) -> bool:
        """Add a user to a party. Returns False if party doesn't exist or is full."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False

        max_users = self._config.MAX_USERS_PER_PARTY
        if max_users > 0 and len(party["users"]) >= max_users:
            return False

        party["users"][sid] = username
        return True

    def remove_user(self, party_id: str, sid: str) -> bool:
        """Remove a user from a party. Returns True if the party was deleted."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False

        party["users"].pop(sid, None)
        if "drift_strikes" in party:
            party["drift_strikes"].pop(sid, None)
        party.get("user_streams", {}).pop(sid, None)

        if len(party["users"]) == 0 and party_id != self.static_party_id:
            del self.watch_parties[party_id]
            self._logger.info(f"Party deleted (last user left): {party_id}")
            return True

        return False

    def find_user_party(self, sid: str) -> Optional[str]:
        """Find which party a user is in by their socket ID"""
        for party_id, party in self.watch_parties.items():
            if sid in party["users"]:
                return party_id
        return None

    def get_users(self, party_id: str) -> list:
        """Get list of usernames in party"""
        party = self.watch_parties.get(party_id)
        if party:
            return list(party["users"].values())
        return []

    def set_video(self, party_id: str, video_data: dict):
        party = self.watch_parties.get(party_id)
        if party:
            party["current_video"] = video_data

    def clear_video(self, party_id: str):
        party = self.watch_parties.get(party_id)
        if party:
            party["current_video"] = None
            party["playback_state"] = {
                "playing": False,
                "time": 0,
                "last_update": datetime.now().isoformat(),
            }

    def update_playback_state(self, party_id: str, playing=None, time=None):
        party = self.watch_parties.get(party_id)
        if party:
            if playing is not None:
                party["playback_state"]["playing"] = playing
            if time is not None:
                party["playback_state"]["time"] = time
            party["playback_state"]["last_update"] = datetime.now().isoformat()

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
        party["host_client_id"] = client_id
        party["host_user_id"] = user_id
        party["host_access_token"] = access_token
        party["host_username"] = username
        party["host_is_admin"] = bool(is_admin)
        party["host_left_at"] = None
        return True

    def clear_host(self, party_id: str) -> bool:
        """Wipe all host fields. Library and HLS are now both locked."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        party["host_client_id"] = None
        party["host_user_id"] = None
        party["host_access_token"] = None
        party["host_username"] = None
        party["host_is_admin"] = False
        party["host_left_at"] = None
        return True

    def mark_host_left(self, party_id: str) -> bool:
        """Stamp host_left_at without clearing the token.

        Transitions the party to PLAYING-ONLY (library locked, HLS still
        served on the stored token). A full clear happens later, either
        on grace expiry or on video_ended/stop_video.
        """
        party = self.watch_parties.get(party_id)
        if not party or not party.get("host_access_token"):
            return False
        party["host_left_at"] = datetime.now().isoformat()
        return True

    def has_host_token(self, party_id: str) -> bool:
        """True iff an Emby access token is stored (HLS usable)."""
        party = self.watch_parties.get(party_id)
        return bool(party and party.get("host_access_token"))

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
            was_active = bool(party.get("binge_watch_active"))
            pending = party.get("pending_auto_advance")
            if not was_active and not pending:
                continue
            if pending:
                task = pending.get("task")
                if task and not task.done():
                    task.cancel()
                party["pending_auto_advance"] = None
            party["binge_watch_active"] = False
            affected.append(party_id)
        return affected

    def is_unlocked(self, party_id: str) -> bool:
        """True iff a host is present and the library is browsable."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        return bool(party.get("host_access_token")) and party.get("host_left_at") is None

    def is_playing_only(self, party_id: str) -> bool:
        """True iff host has left but HLS is still serving a current video."""
        party = self.watch_parties.get(party_id)
        if not party:
            return False
        return (
            bool(party.get("host_access_token"))
            and party.get("host_left_at") is not None
            and party.get("current_video") is not None
        )

    def get_host_token(self, party_id: str) -> Optional[str]:
        """Return the host's Emby access token, or None when fully locked."""
        party = self.watch_parties.get(party_id)
        if not party:
            return None
        return party.get("host_access_token")

    def get_host_user_id(self, party_id: str) -> Optional[str]:
        """Return the host's Emby user id (used for Emby API calls)."""
        party = self.watch_parties.get(party_id)
        if not party:
            return None
        return party.get("host_user_id")

    def members_list(self, party_id: str) -> list:
        """Return [{username, avatar_uuid}, ...] for everyone in the party.

        Combines `party.users` (sid -> name) with `party.participants`
        (client_id keyed metadata) so the frontend can render the
        right avatar per member. Used by user_joined / user_left /
        chat_message emits.
        """
        party = self.watch_parties.get(party_id)
        if not party:
            return []
        sid_client_ids = party.get("sid_client_ids", {})
        participants = party.get("participants", {})
        out = []
        for sid, username in party.get("users", {}).items():
            cid = sid_client_ids.get(sid)
            p = participants.get(cid) if cid else None
            out.append({
                "username": username,
                "avatar_uuid": p.get("avatar_uuid") if p else None,
            })
        return out
