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


class CatalogQueryV2(V2Model):
    scope: CatalogScopeV2 = Field(default_factory=CatalogScopeV2)
    page: CatalogPageV2 = Field(default_factory=CatalogPageV2)
    sort: CatalogSortV2 = Field(default_factory=CatalogSortV2)
    search_term: str | None = Field(default=None, max_length=200)


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


__all__ = [
    "ActionResultV2",
    "CatalogQueryV2",
    "FavoriteMutationV2",
    "FavoriteResultV2",
    "LoginRequest",
    "LoginResponseV2",
    "MediaItemDetailsV2",
    "MediaItemV2",
    "MediaPageV2",
    "MediaServerInfoV2",
    "PlayedMutationV2",
    "PlayedResultV2",
    "PlaylistCreateV2",
    "PlaylistCreatedV2",
    "PlaylistItemAddV2",
]
