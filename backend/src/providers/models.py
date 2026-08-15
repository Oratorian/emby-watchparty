"""Provider-neutral media-server domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

import httpx

MediaServerType = Literal["emby", "jellyfin"]


class PlaybackMethod(StrEnum):
    HLS_COPY = "hls_copy"
    HLS_REMUX = "hls_remux"
    HLS_TRANSCODE = "hls_transcode"


class PlaybackEventType(StrEnum):
    START = "start"
    PROGRESS = "progress"
    STOP = "stop"


@dataclass(frozen=True)
class ProviderIdentity:
    type: MediaServerType
    display_name: str


@dataclass(frozen=True, repr=False)
class ProviderCredentials:
    access_token: str
    user_id: str

    def __repr__(self) -> str:
        return f"ProviderCredentials(user_id={self.user_id!r}, access_token=<redacted>)"


@dataclass(frozen=True)
class AuthenticatedUser:
    credentials: ProviderCredentials
    username: str
    is_admin: bool


@dataclass(frozen=True)
class UserMediaState:
    playback_position_seconds: float = 0.0
    played_percentage: float | None = None
    played: bool = False
    favorite: bool = False


@dataclass(frozen=True)
class MediaItem:
    id: str
    name: str
    kind: str = "other"
    collection_kind: str | None = None
    overview: str = ""
    runtime_seconds: float | None = None
    production_year: int | None = None
    parent_id: str | None = None
    series_id: str | None = None
    series_name: str | None = None
    season_id: str | None = None
    season_name: str | None = None
    index_number: int | None = None
    parent_index_number: int | None = None
    is_folder: bool = False
    is_playable: bool = False
    is_browsable: bool = False
    has_primary_image: bool = False
    backdrop_count: int = 0
    primary_image_aspect_ratio: float | None = None
    user_state: UserMediaState = field(default_factory=UserMediaState)
    media_source_count: int = 0


@dataclass(frozen=True)
class MediaItemDetails(MediaItem):
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    people: tuple[dict, ...] = ()
    studios: tuple[str, ...] = ()
    official_rating: str | None = None
    community_rating: float | None = None
    critic_rating: float | None = None


@dataclass(frozen=True)
class MediaPage:
    items: tuple[MediaItem, ...]
    total: int | None = None
    start: int = 0


@dataclass(frozen=True)
class PlaybackRequest:
    item_id: str
    credentials: ProviderCredentials
    media_source_id: str | None = None
    audio_index: int | None = None
    subtitle_index: int | None = None
    quality: str = "auto"
    start_seconds: float = 0.0
    client_codecs: frozenset[str] = frozenset({"h264"})


@dataclass(frozen=True)
class HLSResource:
    url: str


@dataclass
class PlaybackPlan:
    stream_id: str
    item_id: str
    media_source_id: str
    play_session_id: str
    method: PlaybackMethod
    master: HLSResource
    resources: dict[str, HLSResource] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class PlaybackEvent:
    type: PlaybackEventType
    item_id: str
    media_source_id: str
    play_session_id: str
    position_seconds: float
    credentials: ProviderCredentials
    is_paused: bool = False


@dataclass(frozen=True)
class AssetRequest:
    item_id: str
    kind: str
    credentials: ProviderCredentials
    index: int | None = None
    media_source_id: str | None = None


@dataclass(frozen=True)
class ProviderReadiness:
    reachable: bool
    credentials_valid: bool


class MediaServerError(Exception):
    """Base provider failure safe to translate at router seam."""


class MediaServerUnavailableError(MediaServerError):
    """Selected media server could not be reached."""


class PlaybackPlanError(MediaServerError):
    """Provider could not produce an approved HLS plan."""


class UnsafeProviderResourceError(MediaServerError):
    """Provider returned a resource outside its approved playback roots."""


ProviderResponse = httpx.Response
