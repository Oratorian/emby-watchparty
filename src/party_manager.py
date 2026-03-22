"""
Party Manager Module
Manages watch party state with typed dataclasses
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from src.config import Config
from src.utils import generate_party_code


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


@dataclass
class Party:
    """A single watch party instance"""
    id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    users: Dict[str, str] = field(default_factory=dict)  # sid -> username
    current_video: Optional[VideoInfo] = None
    playback_state: PlaybackState = field(default_factory=PlaybackState)
    drift_strikes: Dict[str, int] = field(default_factory=dict)  # sid -> strike count

    def get_username(self, sid: str) -> str:
        return self.users.get(sid, "Someone")

    def get_user_list(self) -> list:
        return list(self.users.values())

    def user_count(self) -> int:
        return len(self.users)

    def to_sync_dict(self) -> dict:
        """State dict sent to clients on join"""
        return {
            "current_video": self.current_video.to_dict() if self.current_video else None,
            "playback_state": self.playback_state.to_dict(),
        }


class PartyManager:
    """Manages all watch parties and their state"""

    def __init__(self, config: Config, logger: logging.Logger):
        self._parties: Dict[str, Party] = {}
        self._config = config
        self._logger = logger

        # Create static party on startup if configured
        if config.STATIC_SESSION_ENABLED:
            self._create_party(party_id=config.STATIC_SESSION_ID)
            self._logger.info(f"Static session mode: {config.STATIC_SESSION_ID}")

    @property
    def static_party_id(self) -> Optional[str]:
        if self._config.STATIC_SESSION_ENABLED:
            return self._config.STATIC_SESSION_ID
        return None

    def _create_party(self, party_id: str) -> Party:
        """Internal: create party with a specific ID"""
        party = Party(id=party_id)
        self._parties[party_id] = party
        return party

    def create_party(self) -> str:
        """Create a new party with a generated ID. Returns party_id."""
        party_id = generate_party_code(self._parties)
        self._create_party(party_id)
        return party_id

    def get(self, party_id: str) -> Optional[Party]:
        """Get a party by ID, or None"""
        return self._parties.get(party_id)

    def exists(self, party_id: str) -> bool:
        return party_id in self._parties

    def ensure_static_party(self) -> Optional[str]:
        """Recreate the static party if it was deleted. Returns party_id or None."""
        if not self._config.STATIC_SESSION_ENABLED:
            return None
        pid = self._config.STATIC_SESSION_ID
        if pid not in self._parties:
            self._create_party(pid)
            self._logger.info(f"Recreated static party: {pid}")
        return pid

    def add_user(self, party_id: str, sid: str, username: str) -> bool:
        """Add a user to a party. Returns False if party doesn't exist or is full."""
        party = self._parties.get(party_id)
        if not party:
            return False

        max_users = self._config.MAX_USERS_PER_PARTY
        if max_users > 0 and party.user_count() >= max_users:
            return False

        party.users[sid] = username
        return True

    def remove_user(self, party_id: str, sid: str) -> bool:
        """Remove a user from a party. Returns True if the party was deleted."""
        party = self._parties.get(party_id)
        if not party:
            return False

        party.users.pop(sid, None)
        party.drift_strikes.pop(sid, None)

        # Delete empty non-static parties
        if party.user_count() == 0 and party_id != self.static_party_id:
            del self._parties[party_id]
            return True

        return False

    def find_user_party(self, sid: str) -> Optional[str]:
        """Find which party a user is in by their socket ID"""
        for party_id, party in self._parties.items():
            if sid in party.users:
                return party_id
        return None

    def evict_stale_session(self, party_id: str, sid: str):
        """Remove a stale session from a party (e.g. duplicate login)"""
        party = self._parties.get(party_id)
        if party:
            party.users.pop(sid, None)
            party.drift_strikes.pop(sid, None)

    def set_video(self, party_id: str, video: VideoInfo):
        party = self._parties.get(party_id)
        if party:
            party.current_video = video
            party.playback_state.reset()

    def clear_video(self, party_id: str):
        party = self._parties.get(party_id)
        if party:
            party.current_video = None
            party.playback_state.reset()

    def get_all(self) -> Dict[str, Party]:
        return self._parties

    def count(self) -> int:
        return len(self._parties)
