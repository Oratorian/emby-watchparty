"""
Admin Router - Settings management.

Two paths in:
1. **Party-host as admin.** A host whose Emby account has
   `IsAdministrator=true` is automatically admin of the application.
   No separate /admin login is needed; the same party-bound session
   cookie used everywhere else also unlocks /admin.
2. **Standalone login.** Kept so an admin can edit config without
   joining a party. Posts Emby admin credentials to
   `POST /api/admin/login`; the cookie receives an opaque handle while
   the Emby token remains in the bounded server-side session store.
"""

from fastapi import APIRouter, Depends, Request

from backend.src.client_ip import request_client_ip
from backend.src.dependencies import (
    admin_display_name,
    get_admin_session_store,
    get_config,
    get_logger,
    get_media_server,
    get_party_manager,
    get_sio,
    is_admin_authenticated,
    scrub_legacy_admin_session,
)
from backend.src.log_levels import apply_log_levels
from backend.src.providers.models import MediaServerUnavailableError
from backend.src.rate_limit import parse_rate, rate_limit_response
from backend.src.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    RuntimeConfigResponse,
    SuccessResponse,
)


def _client_ip(request: Request) -> str:
    config = request.app.state.config
    return request_client_ip(request, config.TRUSTED_PROXY_CIDRS)


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(
    body: AdminLoginRequest,
    request: Request,
    provider=Depends(get_media_server),
    admin_session_store=Depends(get_admin_session_store),
    logger=Depends(get_logger),
):
    """Standalone admin login. Useful when not currently in a party.

    Hosts who are already inside a party with admin policy do NOT need
    to call this -- their party-bound cookie already grants /admin
    access via is_admin_authenticated().

    Rate limited per IP. Prevents this
    endpoint from being used as a credential-stuffing oracle against
    every Emby admin account -- previously there was no throttle at
    all and the endpoint returned a clean success/failure signal.
    """
    if request.app.state.config.ENABLE_RATE_LIMITING:
        ip = _client_ip(request)
        limit, window = parse_rate(
            getattr(request.app.state.config, "RATE_LIMIT_LOGIN", "10 per 15 minutes")
        )
        decision = request.app.state.rate_limiter.check(
            f"admin-login:{ip}", limit=limit, window_seconds=window
        )
        if not decision.allowed:
            logger.warning(
                f"Admin login rate-limited for IP {ip} (retry in {decision.retry_after}s)"
            )
            return rate_limit_response("login attempts", decision.retry_after)
    try:
        auth = await provider.authenticate_user(body.username, body.password)
    except MediaServerUnavailableError:
        return {
            "success": False,
            "message": (
                f"{provider.identity.display_name} server unavailable; verify MEDIA_SERVER_URL"
            ),
        }
    if not auth:
        return {"success": False, "message": "Invalid credentials"}
    try:
        if not auth.is_admin:
            logger.warning(f"Admin login denied for '{body.username}' -- not administrator")
            return {
                "success": False,
                "message": "This account does not have administrator privileges",
            }

        username = auth.username
        old_handle = request.session.pop("admin_session_id", None)
        admin_session_store.revoke(old_handle)
        scrub_legacy_admin_session(request.session)
        request.session["admin_session_id"] = admin_session_store.create(
            username=username,
            access_token=auth.credentials.access_token,
            user_id=auth.credentials.user_id,
            is_admin=True,
        )
        logger.info(f"Admin login: '{username}'")
        return {"success": True}

    except Exception as e:
        logger.error("Admin login error=%s", type(e).__name__)
        return {"success": False, "message": "Authentication failed"}


@router.post("/logout", response_model=SuccessResponse)
def admin_logout(
    request: Request,
    admin_session_store=Depends(get_admin_session_store),
):
    """Clear the standalone admin session.

    Does NOT touch host status -- a host who is also admin via Emby
    policy stays admin as long as they remain host.
    """
    admin_session_store.revoke(request.session.pop("admin_session_id", None))
    scrub_legacy_admin_session(request.session)
    return {"success": True}


@router.get("/config", response_model=RuntimeConfigResponse)
def get_config_values(
    request: Request,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
    admin_session_store=Depends(get_admin_session_store),
):
    if not is_admin_authenticated(request, party_manager, admin_session_store):
        return {"error": "Not authenticated"}
    return config.get_runtime_dict()


@router.put("/config", response_model=ConfigUpdateResponse)
async def update_config(
    request: Request,
    body: ConfigUpdateRequest,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
    admin_session_store=Depends(get_admin_session_store),
):
    if not is_admin_authenticated(request, party_manager, admin_session_store):
        return ConfigUpdateResponse(success=False)

    # ConfigUpdateRequest allows extra fields (the runtime key set is
    # driven by RuntimeConfig, not a fixed schema), so flatten to a dict
    # for downstream validation. Passing `exclude_unset=True` keeps the
    # env-only guard from tripping on defaulted-but-absent keys.
    payload = body.model_dump(exclude_unset=True)

    env_only = {
        "WATCH_PARTY_BIND",
        "WATCH_PARTY_PORT",
        "APP_PREFIX",
        "SESSION_EXPIRY",
        "MEDIA_SERVER_TYPE",
        "MEDIA_SERVER_URL",
        "MEDIA_SERVER_API_KEY",
        "ENABLE_HLS_TOKEN_VALIDATION",
    }
    env_only_hit = [k for k in payload if k in env_only]
    if env_only_hit:
        return ConfigUpdateResponse(success=False)

    try:
        changed, rejected = config.update_runtime(payload)

        if {"LOG_LEVEL", "CONSOLE_LOG_LEVEL"} & set(changed):
            apply_log_levels(config)
            logger.info(
                f"Log levels reloaded: app={config.LOG_LEVEL}, console={config.CONSOLE_LOG_LEVEL}"
            )

        # File-logging settings can be tuned via the admin panel but the
        # underlying handlers were only built once at boot. Flag these
        # so the UI can show a "restart required" banner instead of
        # silently pretending the change took effect.
        restart_required_keys = {
            "LOG_TO_FILE",
            "LOG_FILE",
            "LOG_FORMAT",
            "LOG_MAX_SIZE",
        }
        restart_required = sorted(set(changed) & restart_required_keys)

        # Static session toggles or id renames need an explicit sync
        # because the static party lives in PartyManager.watch_parties,
        # not in the config object. When the old party is deleted we
        # also need to evict any lingering sockets and revoke HLS tokens
        # so users with active streams or stale cookies stop hitting
        # the now-defunct party.
        if {"STATIC_SESSION_ENABLED", "STATIC_SESSION_ID"} & set(changed):
            _, dissolved = party_manager.sync_static_party()
            if dissolved:
                lifecycle = request.app.state.socket_context["party_lifecycle"]
                await lifecycle.dissolve(dissolved, reason="static_session_disabled")

        # Binge-watch master toggle changed: propagate to every live
        # party so the control-strip button appears / disappears
        # without anyone needing to refresh. The frontend hides the
        # button on available=false and closes any open AutoAdvance
        # modal on the implicit cancel.
        if "BINGE_WATCH_ENABLED" in changed:
            if not config.BINGE_WATCH_ENABLED:
                # Off: cancel any countdown + force-clear the per-party
                # active flag on parties that had it armed, THEN
                # broadcast available=false to every active party. The
                # "only affected" optimisation used to skip parties
                # where the host hadn't clicked the pill, which meant
                # those parties kept rendering the button until reload
                # (contradicting the admin-panel hint). Broadcasting to
                # everyone is cheap and matches the "on" branch's shape.
                party_manager.disable_binge_watch_globally()
                for pid in party_manager.get_all():
                    try:
                        await sio.emit(
                            "binge_watch_state_changed",
                            {
                                "available": False,
                                "active": False,
                            },
                            room=pid,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to emit binge_watch_state_changed to {pid}: {e}")
            else:
                # On: broadcast available=true to EVERY active party so
                # the host's control-strip button materialises right
                # away. The per-party `binge_watch_active` flag is
                # untouched here -- hosts opt in per session via the
                # button -- so we surface whatever value is already on
                # the party (zero for fresh parties, possibly true if
                # the admin off/on cycled while a host had it armed).
                for active_id, active_party in party_manager.get_all().items():
                    try:
                        await sio.emit(
                            "binge_watch_state_changed",
                            {
                                "available": True,
                                "active": bool(active_party.binge_watch_active),
                            },
                            room=active_id,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to emit binge_watch_state_changed to {active_id}: {e}"
                        )

        actor = admin_display_name(request, party_manager, admin_session_store) or "(unknown admin)"
        logger.info(
            f"Admin config updated by '{actor}': changed={changed} "
            f"rejected={rejected} restart_required={restart_required}"
        )
        return ConfigUpdateResponse(
            success=True,
            changed=changed,
            config=config.get_runtime_dict(),
            rejected=rejected,
            restart_required=restart_required,
        )
    except Exception as e:
        logger.error("Config update failed: error=%s", type(e).__name__)
        return ConfigUpdateResponse(success=False)
