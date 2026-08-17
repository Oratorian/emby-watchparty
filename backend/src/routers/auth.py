"""
Auth Router -- become-host / drop-host / status / version.

`POST /api/auth/login` takes Emby credentials from a party-bound caller
and promotes them to host of their current party.
"""

import secrets

from fastapi import APIRouter, Depends, Request

from backend.src import __codename__, __version__
from backend.src.dependencies import (
    get_config,
    get_hls_registry,
    get_http_client,
    get_logger,
    get_media_server,
    get_party_manager,
    get_sio,
    party_host_session_matches,
)
from backend.src.providers.models import MediaServerUnavailableError
from backend.src.schemas import (
    AuthStatusResponse,
    LoginRequest,
    LoginResponse,
    VersionResponse,
)

router = APIRouter(prefix="/api", tags=["auth"])


# Undocumented dev gate. When set in the process environment, the
# in-party "Login to Become Host" endpoint ignores the request body
# and authenticates with these pre-stored Emby credentials instead
# -- so during continuous dev / restart cycles you don't have to
# retype the same admin password into the modal every time the
# backend bounces.
#
# Two env vars must BOTH be present for the gate to activate:
#
#   EMBY_WATCHPARTY_X_DEV_HOST=username:password
#   EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK=true
#
# The ACCEPT_RISK var is a deliberate second key -- it forces anyone
# who copies a `.env` from elsewhere (or restores one from backup) to
# explicitly opt in to "yes I know any party member becomes host for
# free, this is a dev box". Missing ACCEPT_RISK with DEV_HOST set
# fails closed: the gate is OFF, the modal works normally, and a
# loud ERROR fires at startup pointing at the misconfiguration.
#
# Both vars are deliberately NOT in `config.py` (would surface on
# /admin) and NOT in `.env.example` (would be suggested by the
# templated bootstrap). The variable names are intentionally obscure
# so a casual reader of /api/admin/config, /admin, or the source
# tree can't guess at their existence. Operators who want them set
# them directly in the container env or untracked `.env`.
def _env_dev_host_risk_accepted(config) -> bool:
    return (
        config._private_env_value("EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK").strip().lower()
        == "true"
    )


def _env_dev_host_creds(config) -> tuple[str | None, str | None]:
    raw = config._private_env_value("EMBY_WATCHPARTY_X_DEV_HOST").strip()
    if not raw or ":" not in raw:
        return None, None
    # Fail closed when the acknowledgement is missing or set to
    # anything other than the literal string "true". This is the
    # second key that arms the gate -- without it the creds are
    # treated as if they weren't set at all.
    if not _env_dev_host_risk_accepted(config):
        return None, None
    user, _, pw = raw.partition(":")
    user = user.strip()
    pw = pw.strip()
    if not user or not pw:
        return None, None
    return user, pw


@router.post("/auth/login", response_model=LoginResponse)
async def api_login(
    body: LoginRequest,
    request: Request,
    config=Depends(get_config),
    provider=Depends(get_media_server),
    party_manager=Depends(get_party_manager),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
):
    """Become host of the caller's current party.

    Requires a party-bound session cookie (set by /api/party/<id>/join
    or by /api/party/create with REQUIRE_LOGIN=true). Authenticates the
    supplied Emby credentials, stores the resulting access_token on the
    party, and broadcasts host_changed so other members re-render.
    """
    session = request.session
    party_id = session.get("party_id")
    client_id = session.get("client_id")
    if not party_id or not client_id:
        return LoginResponse(
            success=False,
            message="Join a party before logging in",
        )
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        # Stale cookie -- the party went away while we held the session.
        session.pop("party_id", None)
        session.pop("client_id", None)
        session.pop("display_name", None)
        return LoginResponse(
            success=False,
            message="Party no longer exists",
        )

    # Hidden dev shortcut: if EMBY_WATCHPARTY_X_DEV_HOST is set in env
    # (format `user:pass`), ignore whatever was typed in the modal and
    # authenticate with the stored creds instead. Lets a dev hit
    # "Become Host" with junk input and still get promoted across
    # backend restarts. Loud WARNING on every use so it never goes
    # unnoticed if accidentally left set in a non-dev environment.
    dev_user, dev_pw = _env_dev_host_creds(config)
    try:
        if dev_user and dev_pw:
            logger.warning(
                f"Party {party_id}: host login auto-promoted via dev gate "
                f"(EMBY_WATCHPARTY_X_DEV_HOST set, body credentials ignored)"
            )
            auth = await provider.authenticate_user(dev_user, dev_pw)
        else:
            auth = await provider.authenticate_user(body.username, body.password)
    except MediaServerUnavailableError:
        return LoginResponse(
            success=False,
            message=(
                f"{provider.identity.display_name} server unavailable; "
                "ask the operator to verify MEDIA_SERVER_URL"
            ),
        )
    if not auth:
        return LoginResponse(
            success=False,
            message=f"Invalid {provider.identity.display_name} credentials",
        )

    host_session_grant = secrets.token_urlsafe(32)
    party_manager.set_host(
        party_id,
        client_id=client_id,
        session_grant=host_session_grant,
        user_id=auth.credentials.user_id,
        access_token=auth.credentials.access_token,
        username=auth.username,
        is_admin=auth.is_admin,
    )
    session["host_session_grant"] = host_session_grant

    logger.info(
        f"Party {party_id} host changed to '{auth.username}' "
        f"(client_id={client_id[:8]}..., admin={auth.is_admin})"
    )

    # Tell every other member in the room that the party is now unlocked.
    # Access tokens stay server-side; clients only see who the host is.
    await sio.emit(
        "host_changed",
        {
            "host_username": auth.username,
            "host_client_id": client_id,
            "is_admin": auth.is_admin,
            "unlocked": True,
        },
        room=party_id,
    )

    return LoginResponse(
        success=True,
        message="Login successful",
        username=auth.username,
        host_username=auth.username,
        is_host=True,
        is_admin=auth.is_admin,
    )


@router.post("/auth/logout", response_model=LoginResponse)
async def api_logout(
    request: Request,
    party_manager=Depends(get_party_manager),
    hls_registry=Depends(get_hls_registry),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
):
    """Step down as host of the caller's party (does not leave the party).

    No-op when the caller is not the current host. The party stays
    bound to this caller -- they just stop providing the Emby token.
    """
    session = request.session
    party_id = session.get("party_id")
    client_id = session.get("client_id")
    if not party_id or not client_id:
        return LoginResponse(success=True, message="Not in a party")
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        return LoginResponse(success=True, message="Party no longer exists")

    if not party_host_session_matches(
        party,
        client_id,
        session.get("host_session_grant"),
    ):
        # Caller is not host; nothing to clear.
        return LoginResponse(success=True, message="Not the host")

    previous_username = party.host_username

    # Drop the playback plans before clearing the party, because each one holds
    # a copy of this host's media-server token in plan.credentials. The proxy
    # already refuses to serve once host_access_token is gone
    # (_resolve_host_creds returns 401), so nothing is still playable; without
    # this the token simply stays resident until some later teardown happens to
    # fire. A credential the operator has just revoked should not outlive the
    # request that revoked it.
    if hls_registry is not None:
        for stream in list((party.user_streams or {}).values()):
            if stream.stream_id:
                hls_registry.revoke(stream.stream_id)

    party_manager.clear_host(party_id)
    session.pop("host_session_grant", None)
    logger.info(
        f"Party {party_id} host '{previous_username}' stepped down (client_id={client_id[:8]}...)"
    )

    await sio.emit(
        "host_left",
        {"previous_host": previous_username, "reason": "logout"},
        room=party_id,
    )

    return LoginResponse(success=True, message="Logged out")


@router.get("/auth/status", response_model=AuthStatusResponse)
def api_auth_status(
    request: Request,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
):
    """Return the caller's auth state relative to their bound party.

    `authenticated` is true only when the caller is the current host
    of their party. `require_login` reflects the runtime admin toggle
    that gates new-party creation.
    """
    session = request.session
    party_id = session.get("party_id")
    client_id = session.get("client_id")
    if not party_id or not client_id:
        return AuthStatusResponse(
            authenticated=False,
            require_login=config.REQUIRE_LOGIN,
        )
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        return AuthStatusResponse(
            authenticated=False,
            require_login=config.REQUIRE_LOGIN,
            party_id=party_id,
        )

    is_host = party_host_session_matches(
        party,
        client_id,
        session.get("host_session_grant"),
    )
    return AuthStatusResponse(
        authenticated=is_host,
        username=party.host_username if is_host else None,
        is_admin=bool(party.host_is_admin) if is_host else False,
        require_login=config.REQUIRE_LOGIN,
        is_host=is_host,
        party_id=party_id,
        host_username=party.host_username,
        party_unlocked=party_manager.is_unlocked(party_id),
    )


@router.get("/version", response_model=VersionResponse)
async def api_version(
    logger=Depends(get_logger),
    http_client=Depends(get_http_client),
):
    result = VersionResponse(current_version=__version__, codename=__codename__)
    try:
        url = "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
        resp = await http_client.get(url, timeout=5)
        if resp.status_code == 200:
            release = resp.json()
            latest = release.get("tag_name", "").lstrip("v")
            result.latest_version = latest
            result.update_available = bool(latest and latest != __version__)
            result.release_url = release.get("html_url")
    except Exception as e:
        logger.warning("GitHub version check failed: error=%s", type(e).__name__)
    return result
