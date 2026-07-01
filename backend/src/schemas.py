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
    quality: str = "1080p-10000"


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
    # UserData carries the host's per-item state -- specifically
    # PlaybackPositionTicks (in 10M-ticks-per-second units, same scale
    # as RunTimeTicks) and Played (bool). Used by the resume-from-
    # last-position feature: when an item has PlaybackPositionTicks > 0
    # and Played=false, the frontend offers "Resume at HH:MM:SS /
    # Start over" instead of jumping straight to time 0.
    UserData: Optional[dict] = None

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


class MediaVersionInfo(BaseModel):
    """One entry in the multi-version dropdown.

    Emby surfaces alternate versions of the same item (theatrical /
    director's cut, mp4 / mkv, 1080p / 4K HDR) as separate entries in
    `MediaSources`. `name` is the user-visible label Emby's own clients
    show (literally "mp4" / "mkv" for stacked files named
    `Title-mp4.mp4` / `Title-mkv.mkv`, or any custom label for stacked
    `Title - Theatrical.mkv` / `Title - Director's Cut.mkv` style).
    `id` is what we feed back into `MediaSourceId` to switch to that
    version. Closes [#43](https://github.com/Oratorian/emby-watchparty/issues/43).
    """
    id: str
    name: str
    container: Optional[str] = None
    run_time_ticks: Optional[int] = None


class StreamsResponse(BaseModel):
    audio: list[AudioStreamInfo]
    subtitles: list[SubtitleStreamInfo]
    media_source_id: Optional[str] = None
    # Always populated; UI shows a Version dropdown only when len > 1.
    versions: list[MediaVersionInfo] = []


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
    # Values dropped by update_from_dict because they failed type
    # coercion or the shape check (wrong type, null on non-nullable
    # field, unknown key). Frontend surfaces these as "Saved (but X
    # was not applied: <reason>)" so an admin sees the discrepancy
    # instead of a green Saved that quietly kept the old value.
    rejected: list[dict] = []
    # Field names whose value was applied to config.json but where the
    # in-memory subsystem needs a restart to pick it up (LOG_FILE etc).
    # Frontend can render a "restart required" banner listing these.
    restart_required: list[str] = []


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


class PartyListItem(BaseModel):
    """One party in the public index listing (GET /api/party/list)."""
    code: str
    title: Optional[str] = None   # what is being watched; None when no video
    user_count: int
    playing: bool                 # True when a video is active (join -> vote)
    locked: bool                  # True when the party has no host (library locked)


class PartyListResponse(BaseModel):
    """Returned by GET /api/party/list. `parties` is empty when
    REQUIRE_LOGIN is on -- open parties and what they are watching are
    not advertised in that mode."""
    require_login: bool
    parties: list[PartyListItem]


class QualityOption(BaseModel):
    """One entry in the per-user quality dropdown.

    `resolution` is the tier label (e.g. `"1080p"`), `width` / `height`
    are the per-resolution caps Emby honours, `bitrate_kbps` is null for
    the `Auto` option and the resolution-only tiers (360p / 240p / 144p).
    """
    id: str
    label: str
    resolution: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    bitrate_kbps: Optional[int] = None


class QualityOptionsResponse(BaseModel):
    """Returned by GET /api/quality-options. Filtered by the admin's
    `ENABLED_QUALITY_OPTIONS` setting (resolution -> list of enabled
    bitrates); `Auto` is omitted when `FORCE_TRANSCODE` is on (it would
    conflict with always-transcode and let the bitrate balloon on h265
    sources)."""
    options: list[QualityOption]
    default_id: str
