"""Typed watch-party domain state with temporary mapping compatibility."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, MutableMapping
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
class Party(MutableMapping[str, Any]):
    """Typed party aggregate with temporary mapping compatibility."""

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
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    _MAPPED_FIELDS = frozenset({
        "id", "created_at", "users", "participants", "sid_client_ids",
        "current_video", "user_streams", "playback_state", "ready_check",
        "pending_join", "join_cooldown_until", "host_client_id", "host_user_id",
        "host_access_token", "host_is_admin", "host_username", "host_left_at",
        "binge_watch_active", "episode_list", "episode_list_season_id",
        "pending_auto_advance", "generation", "closing", "operation_reservations",
    })

    @classmethod
    def create(cls, party_id: str) -> "Party":
        return cls(id=party_id)

    def __getitem__(self, key: str) -> Any:
        if key in self._MAPPED_FIELDS:
            return getattr(self, key)
        return self._extra[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self._MAPPED_FIELDS:
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def __delitem__(self, key: str) -> None:
        if key in self._MAPPED_FIELDS:
            raise KeyError(f"required party field cannot be deleted: {key}")
        del self._extra[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._MAPPED_FIELDS
        yield from self._extra

    def __len__(self) -> int:
        return len(self._MAPPED_FIELDS) + len(self._extra)

    @property
    def party_id(self) -> str:
        return self.id

    def playback_snapshot(self) -> PlaybackState:
        return PlaybackState(**self.playback_state)
