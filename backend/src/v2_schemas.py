"""Strict provider-neutral REST v2 contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.src.schemas import LoginRequest


class V2Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserMediaStateV2(V2Model):
    playback_position_seconds: float = 0.0
    played_percentage: float | None = None
    played: bool = False
    favorite: bool = False


class MediaItemV2(V2Model):
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
    user_state: UserMediaStateV2
    media_source_count: int = 0


class PersonV2(V2Model):
    id: str
    name: str
    kind: str


class MediaItemDetailsV2(MediaItemV2):
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    people: list[PersonV2] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    official_rating: str | None = None
    community_rating: float | None = None
    critic_rating: float | None = None


class MediaPageV2(V2Model):
    items: list[MediaItemV2]
    total: int | None = None
    start: int = 0


class CatalogScopeV2(V2Model):
    parent_id: str | None = None
    include_kinds: list[str] = Field(default_factory=list)
    media_kinds: list[str] = Field(default_factory=list)
    recursive: bool = False


class CatalogPageV2(V2Model):
    start: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class CatalogSortV2(V2Model):
    field: Literal[
        "name",
        "date_created",
        "premiere_date",
        "year",
        "community_rating",
        "critic_rating",
        "runtime",
        "random",
    ] = "name"
    direction: Literal["ascending", "descending"] = "ascending"


class CatalogFiltersV2(V2Model):
    playstate: Literal["any", "played", "unplayed", "resumable"] = "any"
    favorite: bool | None = None
    duplicates: bool | None = None
    genres: list[str] = Field(default_factory=list)
    official_ratings: list[str] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    person_ids: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    containers: list[str] = Field(default_factory=list)
    video_codecs: list[str] = Field(default_factory=list)
    video_types: list[str] = Field(default_factory=list)
    resolutions: list[Literal["4K", "1080p", "720p", "SD"]] = Field(default_factory=list)
    is_3d: bool | None = None
    audio_codecs: list[str] = Field(default_factory=list)
    audio_layouts: list[str] = Field(default_factory=list)
    audio_languages: list[str] = Field(default_factory=list)
    subtitles: Literal["any", "with", "without"] = "any"
    subtitle_codecs: list[str] = Field(default_factory=list)
    subtitle_languages: list[str] = Field(default_factory=list)
    trailers: Literal["any", "with", "without"] = "any"
    extras: Literal["any", "with", "without"] = "any"
    theme_songs: Literal["any", "with", "without"] = "any"
    theme_videos: Literal["any", "with", "without"] = "any"
    locked: Literal["any", "yes", "no"] = "any"
    overview: Literal["any", "with", "without"] = "any"
    missing_provider_ids: list[Literal["imdb", "tmdb", "tvdb"]] = Field(default_factory=list)


class CatalogQueryV2(V2Model):
    scope: CatalogScopeV2 = Field(default_factory=CatalogScopeV2)
    page: CatalogPageV2 = Field(default_factory=CatalogPageV2)
    sort: CatalogSortV2 = Field(default_factory=CatalogSortV2)
    filters: CatalogFiltersV2 = Field(default_factory=CatalogFiltersV2)
    search_term: str | None = Field(default=None, max_length=200)
    anchor_prefix: str | None = Field(default=None, min_length=1, max_length=8)


class MediaServerInfoV2(V2Model):
    media_server_type: Literal["emby", "jellyfin"]
    display_name: str


class LoginResponseV2(V2Model):
    success: bool
    message: str
    username: str | None = None
    is_host: bool = False
    host_username: str | None = None
    is_admin: bool = False
    media_server_type: Literal["emby", "jellyfin"]


class LogoutResponseV2(V2Model):
    success: bool
    message: str


class AuthStatusV2(V2Model):
    authenticated: bool
    username: str | None = None
    is_admin: bool = False
    require_login: bool = False
    is_host: bool = False
    party_id: str | None = None
    host_username: str | None = None
    party_unlocked: bool = False
    media_server_type: Literal["emby", "jellyfin"]


class FavoriteMutationV2(V2Model):
    favorite: bool


class FavoriteResultV2(V2Model):
    success: bool
    favorite: bool


class PlayedMutationV2(V2Model):
    played: bool


class PlayedResultV2(V2Model):
    success: bool
    played: bool


class PlaylistCreateV2(V2Model):
    name: str = Field(min_length=1, max_length=100)


class PlaylistCreatedV2(V2Model):
    id: str
    name: str


class PlaylistItemAddV2(V2Model):
    item_id: str = Field(min_length=1, max_length=200)


class ActionResultV2(V2Model):
    success: bool


class IntroSegmentV2(V2Model):
    has_intro: bool
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None


class AudioStreamV2(V2Model):
    index: int
    language: str
    display_language: str
    codec: str
    channels: int = 0
    is_default: bool = False
    title: str = ""


class SubtitleStreamV2(V2Model):
    index: int
    language: str
    display_language: str
    codec: str
    is_default: bool = False
    is_forced: bool = False
    is_external: bool = False
    is_text: bool = False
    is_image: bool = False
    title: str = ""


class MediaVersionV2(V2Model):
    id: str
    name: str
    container: str | None = None
    runtime_seconds: float | None = None


class StreamCatalogV2(V2Model):
    audio: list[AudioStreamV2]
    subtitles: list[SubtitleStreamV2]
    media_source_id: str | None = None
    versions: list[MediaVersionV2]


__all__ = [
    "ActionResultV2",
    "AudioStreamV2",
    "AuthStatusV2",
    "CatalogFiltersV2",
    "CatalogQueryV2",
    "FavoriteMutationV2",
    "FavoriteResultV2",
    "IntroSegmentV2",
    "LoginRequest",
    "LoginResponseV2",
    "LogoutResponseV2",
    "MediaItemDetailsV2",
    "MediaItemV2",
    "MediaPageV2",
    "MediaServerInfoV2",
    "MediaVersionV2",
    "PlayedMutationV2",
    "PlayedResultV2",
    "PlaylistCreateV2",
    "PlaylistCreatedV2",
    "PlaylistItemAddV2",
    "StreamCatalogV2",
    "SubtitleStreamV2",
]
