"""
Pydantic models for API request/response schemas
Auto-generates OpenAPI documentation at /docs
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    username: str | None = None
    is_host: bool = False
    host_username: str | None = None
    is_admin: bool = False


class AuthStatusResponse(BaseModel):
    """Reflects the caller's relationship to their current party.

    `authenticated` is true iff this caller has a party-bound session
    AND is currently the host of that party. `party_id` is the party
    the caller is bound to (cookie state), or None.
    """

    authenticated: bool
    username: str | None = None
    is_admin: bool = False
    require_login: bool = False
    is_host: bool = False
    party_id: str | None = None
    host_username: str | None = None
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

    client_id: str | None = None
    display_name: str | None = None
    username: str | None = None
    password: str | None = None


class CreatePartyResponse(BaseModel):
    party_id: str
    url: str
    is_host: bool = False
    host_username: str | None = None
    is_admin: bool = False
    message: str | None = None


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
    avatar_uuid: str | None = None


class JoinPartyResponse(BaseModel):
    success: bool
    message: str | None = None
    party_id: str | None = None
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
    stream_url_base: str | None = None
    audio_index: int | None = None
    subtitle_index: int | None = None
    media_source_id: str | None = None
    play_session_id: str | None = None
    run_time_seconds: float | None = None
    selected_by: str | None = None
    quality: str = "1080p-10000"


class PartyInfoResponse(BaseModel):
    id: str
    users: list[str]
    current_video: VideoInfoSchema | None = None
    playback_state: PlaybackStateSchema


# ============== Library ==============


class LibraryItem(BaseModel):
    """A library item (movie, series, episode, season, folder, etc).
    Fields are a pragmatic subset of what Emby returns -- additional fields
    are allowed via the model config."""

    Id: str
    Name: str
    Type: str | None = None
    ServerId: str | None = None
    ImageTags: dict | None = None
    BackdropImageTags: list[str] | None = None
    PrimaryImageAspectRatio: float | None = None
    ProductionYear: int | None = None
    Overview: str | None = None
    RunTimeTicks: int | None = None
    IsFolder: bool | None = None
    ParentId: str | None = None
    SeriesId: str | None = None
    SeriesName: str | None = None
    SeasonId: str | None = None
    SeasonName: str | None = None
    IndexNumber: int | None = None
    ParentIndexNumber: int | None = None
    CollectionType: str | None = None
    UserData: dict | None = None

    model_config = ConfigDict(extra="allow")


class LibraryItemsResponse(BaseModel):
    """Emby item list response, used by /api/libraries, /api/items, /api/search."""

    Items: list[LibraryItem] = []
    TotalRecordCount: int | None = None
    StartIndex: int = 0

    model_config = ConfigDict(extra="allow")


class LibraryPrefixesResponse(BaseModel):
    Prefixes: list[str] = []


class StrictApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LibraryQueryScope(StrictApiModel):
    parent_id: str | None = None
    include_item_types: list[str] = Field(default_factory=list)
    media_types: list[str] = Field(default_factory=list)
    recursive: bool = False


class LibraryQueryPage(StrictApiModel):
    start_index: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class LibraryQuerySort(StrictApiModel):
    field: Literal[
        "SortName",
        "DateCreated",
        "PremiereDate",
        "ProductionYear",
        "CommunityRating",
        "CriticRating",
        "Runtime",
        "Random",
    ] = "SortName"
    direction: Literal["Ascending", "Descending"] = "Ascending"


class LibraryQueryFilters(StrictApiModel):
    playstate: Literal["any", "played", "unplayed", "resumable"] = "any"
    favorite: bool | None = None
    duplicates: bool | None = None
    genres: list[str] = Field(default_factory=list)
    official_ratings: list[str] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    containers: list[str] = Field(default_factory=list)
    video_codecs: list[str] = Field(default_factory=list)
    video_types: list[str] = Field(default_factory=list)
    resolutions: list[str] = Field(default_factory=list)
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
    missing_provider_ids: list[Literal["imdb", "tmdb", "tvdb"]] = Field(
        default_factory=list
    )


class LibraryQueryRequest(StrictApiModel):
    scope: LibraryQueryScope = Field(default_factory=LibraryQueryScope)
    page: LibraryQueryPage = Field(default_factory=LibraryQueryPage)
    sort: LibraryQuerySort = Field(default_factory=LibraryQuerySort)
    filters: LibraryQueryFilters = Field(default_factory=LibraryQueryFilters)
    search_term: str | None = Field(default=None, max_length=200)


class ItemDetailsResponse(BaseModel):
    """Single item with extended details. Wraps a LibraryItem plus any
    additional fields Emby returns for that item type."""

    Id: str
    Name: str
    Type: str | None = None
    Overview: str | None = None
    ProductionYear: int | None = None
    RunTimeTicks: int | None = None
    People: list[dict] | None = None
    Genres: list[str] | None = None
    Studios: list[dict] | None = None
    MediaSources: list[dict] | None = None
    MediaStreams: list[dict] | None = None
    # UserData carries the host's per-item state -- specifically
    # PlaybackPositionTicks (in 10M-ticks-per-second units, same scale
    # as RunTimeTicks) and Played (bool). Used by the resume-from-
    # last-position feature: when an item has PlaybackPositionTicks > 0
    # and Played=false, the frontend offers "Resume at HH:MM:SS /
    # Start over" instead of jumping straight to time 0.
    UserData: dict | None = None

    model_config = ConfigDict(extra="allow")


# ============== Media ==============


class IntroResponse(BaseModel):
    hasIntro: bool
    start: float | None = None
    end: float | None = None
    duration: float | None = None


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
    container: str | None = None
    run_time_ticks: int | None = None


class StreamsResponse(BaseModel):
    audio: list[AudioStreamInfo]
    subtitles: list[SubtitleStreamInfo]
    media_source_id: str | None = None
    # Always populated; UI shows a Version dropdown only when len > 1.
    versions: list[MediaVersionInfo] = []


# ============== Version ==============


class VersionResponse(BaseModel):
    current_version: str
    codename: str
    latest_version: str | None = None
    update_available: bool = False
    release_url: str | None = None


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
    message: str | None = None


class SuccessResponse(BaseModel):
    """Generic success response used by logout endpoints."""

    success: bool


class ConfigUpdateRequest(BaseModel):
    """Request body for PUT /api/admin/config.

    The set of updatable runtime keys is driven by the config module
    (RuntimeConfig) rather than a fixed schema, so this model allows
    arbitrary extra fields; the server validates each one against the
    live config's expected type and rejects unknown / mistyped keys via
    the `rejected` list in the response.

    Boot-only env keys (WATCH_PARTY_BIND / WATCH_PARTY_PORT /
    APP_PREFIX / SESSION_EXPIRY / EMBY_SERVER_URL / EMBY_API_KEY) are
    rejected up front with `success: false` and no partial write.

    Example: `{"LOG_LEVEL": "DEBUG", "REQUIRE_LOGIN": true}`.
    """

    model_config = ConfigDict(extra="allow")


class ConfigUpdateResponse(BaseModel):
    success: bool
    changed: list[str] = []
    config: dict | None = None
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

    error: str | None = None

    model_config = ConfigDict(extra="allow")


# ============== Party (extras) ==============


class StaticSessionResponse(BaseModel):
    """Returned by GET /api/party/static-session.
    party_id is null when static session mode is disabled."""

    party_id: str | None = None


class PartyExistsResponse(BaseModel):
    """Returned by GET /api/party/<id>/exists. Boolean probe used by
    the join screen to validate a party code before issuing the cookie."""

    exists: bool


class PartyListItem(BaseModel):
    """One party in the public index listing (GET /api/party/list)."""

    code: str
    title: str | None = None  # what is being watched; None when no video
    user_count: int
    playing: bool  # True when a video is active (join -> vote)
    locked: bool  # True when the party has no host (library locked)


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
    resolution: str | None = None
    width: int | None = None
    height: int | None = None
    bitrate_kbps: int | None = None


class QualityOptionsResponse(BaseModel):
    """Returned by GET /api/quality-options. Filtered by the admin's
    `ENABLED_QUALITY_OPTIONS` setting (resolution -> list of enabled
    bitrates); `Auto` is omitted when `FORCE_TRANSCODE` is on (it would
    conflict with always-transcode and let the bitrate balloon on h265
    sources)."""

    options: list[QualityOption]
    default_id: str
