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
    """Result of /api/auth/login (become host) and /api/auth/logout.

    On a successful become-host, host_username carries the Emby account
    name the caller is now hosting under.
    """
    success: bool
    message: str
    username: Optional[str] = None
    is_host: bool = False
    host_username: Optional[str] = None
    is_admin: bool = False


class AuthStatusResponse(BaseModel):
    """Reflects the caller's relationship to their current party.

    `authenticated` is true iff this caller has a party-bound session
    AND is currently the host of that party. `party_id` is the party
    the caller is bound to (cookie state), or None.
    """
    authenticated: bool
    username: Optional[str] = None
    is_admin: bool = False
    require_login: bool = False
    is_host: bool = False
    party_id: Optional[str] = None
    host_username: Optional[str] = None
    party_unlocked: bool = False


# ============== Party ==============

class CreatePartyRequest(BaseModel):
    """Body for POST /api/party/create.

    When `REQUIRE_LOGIN=true`, `username` and `password` are required:
    the creator authenticates with Emby and becomes host atomically.
    `client_id` is the caller's persistent identifier from localStorage
    (used to bind the session cookie when becoming host).
    `display_name` is shown in chat / user lists.
    """
    client_id: Optional[str] = None
    display_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class CreatePartyResponse(BaseModel):
    party_id: str
    url: str
    is_host: bool = False
    host_username: Optional[str] = None
    is_admin: bool = False
    message: Optional[str] = None


class JoinPartyRequest(BaseModel):
    """Body for POST /api/party/<id>/join.

    Sets up the party-bound session cookie. Anonymous (no Emby
    credentials). The cookie carries the supplied `client_id` and
    `display_name` so subsequent Socket.IO connect / HTTP requests
    can be attributed back to this caller. `avatar_uuid` is optional
    -- when present, members of the party see this caller's chosen
    avatar instead of the generated fallback.
    """
    client_id: str
    display_name: str
    avatar_uuid: Optional[str] = None


class JoinPartyResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    party_id: Optional[str] = None
    is_host: bool = False
    party_unlocked: bool = False


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


# ============== Library ==============

class LibraryItem(BaseModel):
    """A library item (movie, series, episode, season, folder, etc).
    Fields are a pragmatic subset of what Emby returns -- additional fields
    are allowed via the model config."""
    Id: str
    Name: str
    Type: Optional[str] = None
    ServerId: Optional[str] = None
    ImageTags: Optional[dict] = None
    BackdropImageTags: Optional[list[str]] = None
    PrimaryImageAspectRatio: Optional[float] = None
    ProductionYear: Optional[int] = None
    Overview: Optional[str] = None
    RunTimeTicks: Optional[int] = None
    IsFolder: Optional[bool] = None
    ParentId: Optional[str] = None
    SeriesId: Optional[str] = None
    SeriesName: Optional[str] = None
    SeasonId: Optional[str] = None
    SeasonName: Optional[str] = None
    IndexNumber: Optional[int] = None
    ParentIndexNumber: Optional[int] = None
    CollectionType: Optional[str] = None
    UserData: Optional[dict] = None

    class Config:
        extra = "allow"


class LibraryItemsResponse(BaseModel):
    """Emby item list response, used by /api/libraries, /api/items, /api/search."""
    Items: list[LibraryItem] = []
    TotalRecordCount: Optional[int] = None

    class Config:
        extra = "allow"


class ItemDetailsResponse(BaseModel):
    """Single item with extended details. Wraps a LibraryItem plus any
    additional fields Emby returns for that item type."""
    Id: str
    Name: str
    Type: Optional[str] = None
    Overview: Optional[str] = None
    ProductionYear: Optional[int] = None
    RunTimeTicks: Optional[int] = None
    People: Optional[list[dict]] = None
    Genres: Optional[list[str]] = None
    Studios: Optional[list[dict]] = None
    MediaSources: Optional[list[dict]] = None
    MediaStreams: Optional[list[dict]] = None

    class Config:
        extra = "allow"


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


class HealthResponse(BaseModel):
    """Liveness probe payload.

    Intentionally minimal: returns 200 as long as the process is up and
    can route the request. Does NOT contact Emby, the DB, or anything
    else, so a transient upstream blip will not flap a container's
    healthcheck and trigger restart loops.
    """
    status: str = "ok"
    version: str
    codename: str


# ============== Admin ==============

class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    success: bool
    message: Optional[str] = None


class SuccessResponse(BaseModel):
    """Generic success response used by logout endpoints."""
    success: bool


class ConfigUpdateResponse(BaseModel):
    success: bool
    changed: list[str] = []
    config: Optional[dict] = None


class RuntimeConfigResponse(BaseModel):
    """Runtime config values returned by GET /api/admin/config.
    Extra fields are allowed because the set of runtime keys is driven
    by the config module rather than a fixed schema."""
    error: Optional[str] = None

    class Config:
        extra = "allow"


# ============== Party (extras) ==============

class StaticSessionResponse(BaseModel):
    """Returned by GET /api/party/static-session.
    party_id is null when static session mode is disabled."""
    party_id: Optional[str] = None


class PartyExistsResponse(BaseModel):
    """Returned by GET /api/party/<id>/exists. Boolean probe used by
    the join screen to validate a party code before issuing the cookie."""
    exists: bool
