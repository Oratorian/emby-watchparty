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
    """Result of /api/v2/auth/login (become host) and /api/v2/auth/logout.

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

# Only the filter-rail models survive here. Everything else in this section
# described the v1 library and media routes, which /api/v2 replaced; the v2
# surface is modelled in v2_schemas.py.


class StrictApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterOption(StrictApiModel):
    value: str
    label: str


class FilterControl(StrictApiModel):
    id: str
    label: str
    kind: Literal["select", "multi", "toggle"]
    values: list[FilterOption] = Field(default_factory=list)


class FilterOptionsResponse(StrictApiModel):
    controls: list[FilterControl]


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


class ReadinessResponse(BaseModel):
    """Readiness probe payload, returned with 200 when ready and 503 when not.

    The 503 is the whole point of the endpoint and was previously undeclared,
    so an operator reading the schema saw an operation that only ever
    succeeded and wired a probe that could not fail. `checks` is what they
    diagnose from: every entry must be true for the overall status to be
    `ready`, so the false one names the subsystem to look at.
    """

    status: str
    checks: dict[str, bool]


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
    APP_PREFIX / SESSION_EXPIRY / MEDIA_SERVER_URL / MEDIA_SERVER_API_KEY) are
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
