"""Typed watch-party domain state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

MediaValue = str | float | int | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


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

    def to_wire(self) -> dict[str, bool | float | str]:
        return {
            "playing": self.playing,
            "time": self.time,
            "last_update": self.last_update,
        }


@dataclass
class UserStream:
    media_source_id: str
    stream_url_base: str
    play_session_id: str | None = None
    audio_index: int | None = None
    subtitle_index: int | None = None
    quality: str = "Auto"
    ready: bool = False
    start_offset: float = 0.0


@dataclass(frozen=True)
class EpisodeRef:
    item_id: str
    name: str
    index_number: int | None = None
    parent_index_number: int | None = None
    series_id: str | None = None
    season_id: str | None = None


@dataclass(frozen=True)
class SelectedMedia:
    item_id: str
    title: str
    overview: str = ""
    run_time_seconds: float | None = None
    media_source_id: str | None = None
    selected_by: str | None = None
    item_type: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    episode_index: int | None = None
    index_number: int | None = None
    next_item_id: str | None = None
    next_item_title: str | None = None

    def to_wire(self) -> dict[str, MediaValue]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "overview": self.overview,
            "run_time_seconds": self.run_time_seconds,
            "media_source_id": self.media_source_id,
            "selected_by": self.selected_by,
            "item_type": self.item_type,
            "series_id": self.series_id,
            "season_id": self.season_id,
            "episode_index": self.episode_index,
            "index_number": self.index_number,
            "next_item_id": self.next_item_id,
            "next_item_title": self.next_item_title,
        }


@dataclass
class JoinVote:
    sid: str
    username: str
    client_id: str | None = None
    requested_at: str = field(default_factory=_now)
    eligible_voters: set[str] = field(default_factory=set)
    votes: dict[str, str] = field(default_factory=dict)
    selector_sid: str | None = None
    timeout_task: asyncio.Task[None] | None = None


@dataclass
class ReadyCheck:
    expected_sids: set[str] = field(default_factory=set)
    ready_sids: set[str] = field(default_factory=set)
    active: bool = True


@dataclass
class AutoAdvance:
    next_item_id: str
    next_title: str
    next_index_number: int | None
    selector_client_id: str | None
    deadline: str
    task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class PlaybackReportSnapshot:
    current_video: SelectedMedia | None
    user_stream: UserStream | None
    host_access_token: str | None
    host_user_id: str | None


@dataclass(frozen=True)
class PlaybackControlCommit:
    client_id: str
    username: str
    report: PlaybackReportSnapshot
    waiting_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgressReportCommit:
    video: SelectedMedia
    stream: UserStream
    host_access_token: str | None
    host_user_id: str | None
    playing: bool


@dataclass(frozen=True)
class DepartureCommit:
    username: str | None
    client_id: str | None
    stream: UserStream | None
    all_ready: bool
    auto_play: bool
    playback_time: float
    playback_playing: bool
    ready_names: tuple[str, ...]
    waiting_names: tuple[str, ...]
    current_video: SelectedMedia | None
    host_access_token: str | None
    host_user_id: str | None


@dataclass(frozen=True)
class ReadyCommit:
    complete: bool
    auto_play: bool
    playback_time: float
    playback_playing: bool
    ready_names: tuple[str, ...]
    waiting_names: tuple[str, ...]


@dataclass
class Party:
    """Typed party aggregate."""

    id: str
    created_at: str = field(default_factory=_now)
    participants: dict[str, Participant] = field(default_factory=dict)
    sid_client_ids: dict[str, str] = field(default_factory=dict)
    current_video: SelectedMedia | None = None
    user_streams: dict[str, UserStream] = field(default_factory=dict)
    playback_state: PlaybackState = field(default_factory=PlaybackState)
    ready_check: ReadyCheck | None = None
    pending_join: JoinVote | None = None
    join_cooldown_until: float = 0.0
    host_client_id: str | None = None
    host_session_grant: str | None = None
    host_user_id: str | None = None
    host_access_token: str | None = None
    host_is_admin: bool = False
    host_username: str | None = None
    host_left_at: str | None = None
    binge_watch_active: bool = False
    episode_list: list[EpisodeRef] | None = None
    episode_list_season_id: str | None = None
    pending_auto_advance: AutoAdvance | None = None
    generation: int = 0
    closing: bool = False
    operation_reservations: dict[str, str] = field(default_factory=dict)
    join_times: dict[str, str] = field(default_factory=dict)
    drift_strikes: dict[str, int] = field(default_factory=dict)
    auto_play_after_ready: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @classmethod
    def create(cls, party_id: str) -> Party:
        return cls(id=party_id)

    @property
    def party_id(self) -> str:
        return self.id

    def playback_snapshot(self) -> PlaybackState:
        return PlaybackState(
            playing=self.playback_state.playing,
            time=self.playback_state.time,
            last_update=self.playback_state.last_update,
        )

    def has_sid(self, sid: str) -> bool:
        return sid in self.sid_client_ids

    def client_id_for_sid(self, sid: str) -> str | None:
        return self.sid_client_ids.get(sid)

    def username_for_sid(self, sid: str, default: str = "Unknown") -> str:
        client_id = self.sid_client_ids.get(sid)
        participant = self.participants.get(client_id) if client_id else None
        return participant.username if participant else default

    def sids(self) -> tuple[str, ...]:
        return tuple(self.sid_client_ids)

    def usernames(self) -> list[str]:
        return [self.username_for_sid(sid) for sid in self.sid_client_ids]

    @property
    def member_count(self) -> int:
        return len(self.sid_client_ids)
