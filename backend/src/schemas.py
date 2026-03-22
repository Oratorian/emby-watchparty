"""
Pydantic models for API request/response schemas
Auto-generates OpenAPI documentation at /docs
"""

from pydantic import BaseModel
from typing import Optional


# ============== Auth ==============

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str
    username: Optional[str] = None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    username: Optional[str] = None
    is_admin: bool = False
    require_login: bool = False


# ============== Party ==============

class CreatePartyResponse(BaseModel):
    party_id: str
    url: str


class PlaybackStateSchema(BaseModel):
    playing: bool = False
    time: float = 0.0
    last_update: str = ""


class VideoInfoSchema(BaseModel):
    item_id: str
    title: str
    overview: str = ""
    stream_url_base: Optional[str] = None
    audio_index: Optional[int] = None
    subtitle_index: Optional[int] = None
    media_source_id: Optional[str] = None
    play_session_id: Optional[str] = None
    run_time_seconds: Optional[float] = None
    selected_by: Optional[str] = None
    quality: str = "1080p-high"


class PartyInfoResponse(BaseModel):
    id: str
    users: list[str]
    current_video: Optional[VideoInfoSchema] = None
    playback_state: PlaybackStateSchema


# ============== Media ==============

class IntroResponse(BaseModel):
    hasIntro: bool
    start: Optional[float] = None
    end: Optional[float] = None
    duration: Optional[float] = None


class AudioStreamInfo(BaseModel):
    index: int
    language: str
    displayLanguage: str
    codec: str
    channels: int = 0
    isDefault: bool = False
    title: str = ""


class SubtitleStreamInfo(BaseModel):
    index: int
    language: str
    displayLanguage: str
    codec: str
    isDefault: bool = False
    isForced: bool = False
    isExternal: bool = False
    isTextSubtitleStream: bool = False
    isPGS: bool = False
    title: str = ""


class StreamsResponse(BaseModel):
    audio: list[AudioStreamInfo]
    subtitles: list[SubtitleStreamInfo]
    media_source_id: Optional[str] = None


# ============== Version ==============

class VersionResponse(BaseModel):
    current_version: str
    codename: str
    latest_version: Optional[str] = None
    update_available: bool = False
    release_url: Optional[str] = None


# ============== Admin ==============

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class ConfigUpdateResponse(BaseModel):
    success: bool
    changed: list[str] = []
    config: Optional[dict] = None
