"""Typed watch-party domain state with temporary mapping compatibility."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


class Party(dict[str, Any]):
    """Typed party aggregate.

    It remains mapping-compatible while legacy event handlers migrate to
    narrow manager operations. New code should use manager methods instead
    of mutating this mapping directly.
    """

    @classmethod
    def create(cls, party_id: str) -> "Party":
        now = _now()
        return cls({
            "id": party_id,
            "created_at": now,
            "users": {},
            "participants": {},
            "sid_client_ids": {},
            "current_video": None,
            "user_streams": {},
            "playback_state": asdict(PlaybackState(last_update=now)),
            "ready_check": None,
            "pending_join": None,
            "join_cooldown_until": 0,
            "host_client_id": None,
            "host_user_id": None,
            "host_access_token": None,
            "host_is_admin": False,
            "host_username": None,
            "host_left_at": None,
            "binge_watch_active": False,
            "episode_list": None,
            "episode_list_season_id": None,
            "pending_auto_advance": None,
        })

    @property
    def party_id(self) -> str:
        return self["id"]

    def playback_snapshot(self) -> PlaybackState:
        return PlaybackState(**self["playback_state"])
