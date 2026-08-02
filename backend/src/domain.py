"""Typed watch-party domain state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat()


@dataclass
class Participant:
    client_id: str
    username: str
    avatar_uuid: str | None = None
    sid: str | None = None
    last_seen: str = field(default_factory=_now)


@dataclass
class PlaybackState:
    playing: bool = False
    time: float = 0.0
    last_update: str = field(default_factory=_now)


@dataclass
class UserStream:
    media_source_id: str
    play_session_id: str | None = None
    audio_index: int | None = None
    subtitle_index: int | None = None
    quality: str = "Auto"
    ready: bool = False


@dataclass
class JoinVote:
    sid: str
    username: str
    eligible_voters: set[str] = field(default_factory=set)
    votes: dict[str, bool] = field(default_factory=dict)
    task: Any = None


@dataclass
class ReadyCheck:
    expected_sids: set[str] = field(default_factory=set)
    ready_sids: set[str] = field(default_factory=set)
    active: bool = True


@dataclass
class AutoAdvance:
    item_id: str
    deadline: float
    task: Any = None


@dataclass
class Party:
    """Typed party aggregate."""

    id: str
    created_at: str = field(default_factory=_now)
    users: dict[str, str] = field(default_factory=dict)
    participants: dict[str, Participant] = field(default_factory=dict)
    sid_client_ids: dict[str, str] = field(default_factory=dict)
    current_video: dict[str, Any] | None = None
    user_streams: dict[str, dict[str, Any]] = field(default_factory=dict)
    playback_state: dict[str, Any] = field(
        default_factory=lambda: {
            "playing": False,
            "time": 0.0,
            "last_update": _now(),
        }
    )
    ready_check: dict[str, Any] | None = None
    pending_join: dict[str, Any] | None = None
    join_cooldown_until: float = 0.0
    host_client_id: str | None = None
    host_user_id: str | None = None
    host_access_token: str | None = None
    host_is_admin: bool = False
    host_username: str | None = None
    host_left_at: str | None = None
    binge_watch_active: bool = False
    episode_list: list[dict[str, Any]] | None = None
    episode_list_season_id: str | None = None
    pending_auto_advance: dict[str, Any] | None = None
    generation: int = 0
    closing: bool = False
    operation_reservations: dict[str, str] = field(default_factory=dict)
    join_times: dict[str, str] = field(default_factory=dict)
    drift_strikes: dict[str, int] = field(default_factory=dict)
    auto_play_after_ready: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @classmethod
    def create(cls, party_id: str) -> "Party":
        return cls(id=party_id)

    @property
    def party_id(self) -> str:
        return self.id

    def playback_snapshot(self) -> PlaybackState:
        return PlaybackState(**self.playback_state)
