"""Strict provider-neutral REST v2 contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

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


class MediaPageV2(V2Model):
    items: list[MediaItemV2]
    total: int | None = None
    start: int = 0


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


__all__ = [
    "LoginRequest",
    "LoginResponseV2",
    "MediaItemV2",
    "MediaPageV2",
    "MediaServerInfoV2",
]
