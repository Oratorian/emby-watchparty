"""
Party Manager Module
Manages watch party state.

During the 2.0 transition, party state is stored as raw dicts (watch_parties)
for backward compatibility with old handlers. The typed dataclasses and clean
API will be used once all handlers are converted to classes in Phase 3.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from backend.src.config import Config
from backend.src.utils import generate_party_code


# =============================================================================
# Typed dataclasses (used by new code, Phase 3+)
# =============================================================================

@dataclass
class PlaybackState:
    """Tracks playback position and state for a party"""
    playing: bool = False
    time: float = 0.0
    last_update: str = field(default_factory=lambda: datetime.now().isoformat())

    def update(self, playing: Optional[bool] = None, time: Optional[float] = None):
        if playing is not None:
            self.playing = playing
        if time is not None:
            self.time = time
        self.last_update = datetime.now().isoformat()

    def reset(self):
        self.playing = False
        self.time = 0.0
        self.last_update = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "playing": self.playing,
            "time": self.time,
            "last_update": self.last_update,
        }


@dataclass
class VideoInfo:
    """Information about the currently playing video"""
    item_id: str
    title: str
    overview: str
    stream_url_base: str
    audio_index: Optional[int]
    subtitle_index: Optional[int]
    media_source_id: str
    play_session_id: Optional[str]
    run_time_seconds: Optional[float]
    selected_by: str
    quality: str

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "overview": self.overview,
            "stream_url_base": self.stream_url_base,
            "audio_index": self.audio_index,
            "subtitle_index": self.subtitle_index,
            "media_source_id": self.media_source_id,
            "play_session_id": self.play_session_id,
            "run_time_seconds": self.run_time_seconds,
            "selected_by": self.selected_by,
            "quality": self.quality,
        }


# =============================================================================
# Party Manager (dict-based internals for backward compatibility)
# =============================================================================

class PartyManager:
    """
    Manages all watch parties and their state.

    Internally stores parties as raw dicts for backward compatibility
    with old-style handlers that access watch_parties[party_id]["users"] etc.
    """

    def __init__(self, config: Config, logger: logging.Logger):
        self.watch_parties: Dict[str, dict] = {}
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

    def _new_party_dict(self, party_id: str) -> dict:
        """Create a raw party dict in the old format"""
        return {
            "id": party_id,
            "created_at": datetime.now().isoformat(),
            "users": {},
            "participants": {},
            "sid_client_ids": {},
            "current_video": None,
            "user_streams": {},
            "playback_state": {
                "playing": False,
                "time": 0,
                "last_update": datetime.now().isoformat(),
            },
            "ready_check": None,
            "pending_join": None,
            # Unix timestamp after which a new late-joiner vote can be
            # triggered. Set after every failed/cancelled vote to prevent
            # spam attacks. None or 0 means no cooldown active.
            "join_cooldown_until": 0,
        }

    def _create_party_dict(self, party_id: str) -> dict:
        """Create and store a party dict"""
        party = self._new_party_dict(party_id)
        self.watch_parties[party_id] = party
        return party

    def create_party(self) -> str:
        """Create a new party with a generated ID. Returns party_id."""
        party_id = generate_party_code(self.watch_parties)
        self._create_party_dict(party_id)
        return party_id

    def get(self, party_id: str) -> Optional[dict]:
        """Get a party dict by ID, or None"""
        return self.watch_parties.get(party_id)

    def exists(self, party_id: str) -> bool:
        return party_id in self.watch_parties

    def get_all(self) -> Dict[str, dict]:
        """Get the raw watch_parties dict (for backward compat)"""
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

    def sync_static_party(self) -> Optional[str]:
        """Reconcile the static party with the current runtime config.

        Called when STATIC_SESSION_ENABLED or STATIC_SESSION_ID changes via
        the admin panel so the change takes effect without a restart:

        - If the static id changed, remove the old party (if it still exists
          and was not repurposed) before creating the new one.
        - If the feature was disabled, remove the previously-created static
          party so it stops responding to joins.
        - If the feature is enabled and the configured party is missing,
          create it.

        Returns the current static party id (or None when disabled).
        """
        cfg_enabled = self._config.STATIC_SESSION_ENABLED
        cfg_id = self._config.STATIC_SESSION_ID.upper() if cfg_enabled else None

        if self._last_static_id and self._last_static_id != cfg_id:
            old = self._last_static_id
            if old in self.watch_parties:
                del self.watch_parties[old]
                self._logger.info(f"Removed previous static party: {old}")

        if cfg_id and cfg_id not in self.watch_parties:
            self._create_party_dict(cfg_id)
            self._logger.info(f"Created static party: {cfg_id}")

        self._last_static_id = cfg_id
        return cfg_id

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
