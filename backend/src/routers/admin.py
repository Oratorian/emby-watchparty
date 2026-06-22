"""
Admin Router - Settings management.

Two paths in:
1. **Party-host as admin.** A host whose Emby account has
   `IsAdministrator=true` is automatically admin of the application.
   No separate /admin login is needed; the same party-bound session
   cookie used everywhere else also unlocks /admin.
2. **Standalone login.** Kept so an admin can edit config without
   joining a party. Posts Emby admin credentials to
   `POST /api/admin/login`; the session gains an `admin_authenticated`
   flag that survives until logout.
"""

from fastapi import APIRouter, Depends, Request
import requests as http_requests

from backend.src.log_levels import apply_log_levels
from backend.src.dependencies import (
    admin_display_name,
    get_config,
    get_emby_client,
    get_logger,
    get_party_manager,
    get_sio,
    get_token_manager,
    is_admin_authenticated,
)
from backend.src.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    ConfigUpdateResponse,
    RuntimeConfigResponse,
    SuccessResponse,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(body: AdminLoginRequest, request: Request,
                emby_client=Depends(get_emby_client), logger=Depends(get_logger)):
    """Standalone admin login. Useful when not currently in a party.

    Hosts who are already inside a party with admin policy do NOT need
    to call this -- their party-bound cookie already grants /admin
    access via is_admin_authenticated().
    """
    try:
        url = f"{emby_client.server_url}/emby/Users/AuthenticateByName"
        headers = {
            "Content-Type": "application/json",
            "X-Emby-Authorization": (
                f'Emby Client="WatchParty", Device="Web", '
                f'DeviceId="{emby_client.device_id}", Version="1.0"'
            ),
        }
        resp = http_requests.post(
            url, headers=headers,
            json={"Username": body.username, "Pw": body.password},
            timeout=15,
        )

        if resp.status_code != 200:
            return {"success": False, "message": "Invalid credentials"}

        data = resp.json()
        user = data.get("User") or {}
        is_admin = user.get("Policy", {}).get("IsAdministrator", False)

        if not is_admin:
            logger.warning(f"Admin login denied for '{body.username}' -- not administrator")
            return {"success": False, "message": "This account does not have administrator privileges"}

        access_token = data.get("AccessToken")
        user_id = user.get("Id")
        if not access_token or not user_id:
            return {"success": False, "message": "Authentication response missing token or user id"}

        request.session["admin_authenticated"] = True
        request.session["admin_username"] = user.get("Name", body.username)
        # Stash the Emby auth so /api/party/create can auto-promote this
        # admin to host without making them log in a second time. The
        # cookie is signed by Starlette's SessionMiddleware; storing the
        # access_token here is the same exposure surface as the cookie
        # itself, which is already used to bind party-host membership.
        request.session["admin_emby_token"] = access_token
        request.session["admin_emby_user_id"] = user_id
        request.session["admin_emby_is_admin"] = True
        logger.info(f"Admin login: '{request.session['admin_username']}'")
        return {"success": True}

    except http_requests.exceptions.Timeout:
        return {"success": False, "message": "Emby server connection timed out"}
    except http_requests.exceptions.RequestException as e:
        logger.error(f"Admin login error: {e}")
        return {"success": False, "message": "Unable to connect to Emby server"}


@router.post("/logout", response_model=SuccessResponse)
def admin_logout(request: Request):
    """Clear the standalone admin session.

    Does NOT touch host status -- a host who is also admin via Emby
    policy stays admin as long as they remain host.
    """
    request.session.pop("admin_authenticated", None)
    request.session.pop("admin_username", None)
    request.session.pop("admin_emby_token", None)
    request.session.pop("admin_emby_user_id", None)
    request.session.pop("admin_emby_is_admin", None)
    return {"success": True}


@router.get("/config", response_model=RuntimeConfigResponse)
def get_config_values(
    request: Request,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
):
    if not is_admin_authenticated(request, party_manager):
        return {"error": "Not authenticated"}
    return config.get_runtime_dict()


async def _dissolve_party(party_id: str, sio, token_manager, logger):
    """Tear down a party that was just deleted from PartyManager.

    1. Tell every connected member to go back to the index ('party_dissolved').
    2. Close the Socket.IO room so future emits do not reach them.
    3. Revoke every cached HLS token issued for this party so leftover
       stream URLs stop working immediately.
    """
    try:
        await sio.emit(
            "party_dissolved",
            {"party_id": party_id, "reason": "static_session_disabled"},
            room=party_id,
        )
    except Exception as e:
        logger.warning(f"Failed to emit party_dissolved for {party_id}: {e}")
    try:
        await sio.close_room(party_id)
    except Exception as e:
        logger.warning(f"Failed to close room {party_id}: {e}")
    try:
        token_manager.revoke_party(party_id)
    except Exception as e:
        logger.warning(f"Failed to revoke tokens for {party_id}: {e}")


@router.put("/config", response_model=ConfigUpdateResponse)
async def update_config(
    request: Request,
    body: dict,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
    token_manager=Depends(get_token_manager),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
):
    if not is_admin_authenticated(request, party_manager):
        return ConfigUpdateResponse(success=False)

    env_only = {
        'WATCH_PARTY_BIND', 'WATCH_PARTY_PORT', 'APP_PREFIX',
        'SESSION_EXPIRY',
        'EMBY_SERVER_URL', 'EMBY_API_KEY',
    }
    rejected = [k for k in body.keys() if k in env_only]
    if rejected:
        return ConfigUpdateResponse(success=False)

    try:
        changed = config.update_runtime(body)

        if {'LOG_LEVEL', 'CONSOLE_LOG_LEVEL'} & set(changed):
            apply_log_levels(config)
            logger.info(
                f"Log levels reloaded: app={config.LOG_LEVEL}, "
                f"console={config.CONSOLE_LOG_LEVEL}"
            )

        # Static session toggles or id renames need an explicit sync
        # because the static party lives in PartyManager.watch_parties,
        # not in the config object. When the old party is deleted we
        # also need to evict any lingering sockets and revoke HLS tokens
        # so users with active streams or stale cookies stop hitting
        # the now-defunct party.
        if {'STATIC_SESSION_ENABLED', 'STATIC_SESSION_ID'} & set(changed):
            _, dissolved = party_manager.sync_static_party()
            if dissolved:
                await _dissolve_party(dissolved, sio, token_manager, logger)

        # Binge-watch master toggle changed: propagate to every live
        # party so the control-strip button appears / disappears
        # without anyone needing to refresh. The frontend hides the
        # button on available=false and closes any open AutoAdvance
        # modal on the implicit cancel.
        if 'BINGE_WATCH_ENABLED' in changed:
            if not config.BINGE_WATCH_ENABLED:
                # Off: cancel any countdown, force-clear per-party active
                # flag, then broadcast only to parties that were actually
                # affected (saves a round-trip on the silent majority).
                affected = party_manager.disable_binge_watch_globally()
                for affected_id in affected:
                    try:
                        await sio.emit("binge_watch_state_changed", {
                            "available": False, "active": False,
                        }, room=affected_id)
                    except Exception as e:
                        logger.warning(
                            f"Failed to emit binge_watch_state_changed to {affected_id}: {e}"
                        )
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
                        await sio.emit("binge_watch_state_changed", {
                            "available": True,
                            "active": bool(active_party.get("binge_watch_active")),
                        }, room=active_id)
                    except Exception as e:
                        logger.warning(
                            f"Failed to emit binge_watch_state_changed to {active_id}: {e}"
                        )

        actor = admin_display_name(request, party_manager) or "(unknown admin)"
        logger.info(f"Admin config updated by '{actor}': {changed}")
        return ConfigUpdateResponse(success=True, changed=changed, config=config.get_runtime_dict())
    except Exception as e:
        logger.error(f"Config update failed: {e}")
        return ConfigUpdateResponse(success=False)


