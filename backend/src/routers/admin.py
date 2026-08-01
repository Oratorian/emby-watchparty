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

import time as _time
from collections import deque
from threading import Lock

from fastapi import APIRouter, Depends, Request
import requests as http_requests

from backend.src.log_levels import apply_log_levels
from backend.src.dependencies import (
    admin_display_name,
    get_admin_session_store,
    get_config,
    get_emby_client,
    get_logger,
    get_party_manager,
    get_sio,
    get_token_manager,
    is_admin_authenticated,
)


# --- /api/admin/login rate limiter -------------------------------------
# In-memory sliding window per client IP. Hardcoded because the
# admin-panel ENABLE_RATE_LIMITING / RATE_LIMIT_* fields are documented
# as advisory and don't drive any real limiter today (audit finding);
# rewiring that plumbing is out of scope for this hardening pass, and a
# working limit on the credential-oracle endpoint is much more
# important than making it configurable. Values match typical brute-
# force protection: 10 attempts / 15 minutes per IP.
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECS = 15 * 60
_LOGIN_ATTEMPTS: dict[str, deque[float]] = {}
_LOGIN_ATTEMPTS_LOCK = Lock()


def _login_rate_limited(client_ip: str) -> tuple[bool, int]:
    """Return (is_limited, retry_after_seconds)."""
    now = _time.monotonic()
    cutoff = now - _LOGIN_WINDOW_SECS
    with _LOGIN_ATTEMPTS_LOCK:
        bucket = _LOGIN_ATTEMPTS.setdefault(client_ip, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _LOGIN_MAX_ATTEMPTS:
            retry_after = int(_LOGIN_WINDOW_SECS - (now - bucket[0])) + 1
            return True, max(1, retry_after)
        bucket.append(now)
        return False, 0


def _client_ip(request: Request) -> str:
    """Best-effort caller IP. Trusts X-Forwarded-For's LAST hop (nearest
    reverse-proxy) since the app is expected to sit behind one; a
    misbehaving direct client can only spoof their own bucket, not
    another IP's."""
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "0.0.0.0"
from backend.src.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    RuntimeConfigResponse,
    SuccessResponse,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(body: AdminLoginRequest, request: Request,
                emby_client=Depends(get_emby_client), logger=Depends(get_logger),
                admin_session_store=Depends(get_admin_session_store)):
    """Standalone admin login. Useful when not currently in a party.

    Hosts who are already inside a party with admin policy do NOT need
    to call this -- their party-bound cookie already grants /admin
    access via is_admin_authenticated().

    Rate limited per IP (see _login_rate_limited). Prevents this
    endpoint from being used as a credential-stuffing oracle against
    every Emby admin account -- previously there was no throttle at
    all and the endpoint returned a clean success/failure signal.
    """
    ip = _client_ip(request)
    limited, retry_after = _login_rate_limited(ip)
    if limited:
        logger.warning(
            f"Admin login rate-limited for IP {ip} (retry in {retry_after}s)"
        )
        return {
            "success": False,
            "message": (
                f"Too many login attempts. Try again in {retry_after} seconds."
            ),
        }
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
        # admin to host without making them log in a second time.
        #
        # The credentials go into a SERVER-SIDE store and only the opaque
        # handle is put in the cookie. SessionMiddleware signs the cookie
        # but does not encrypt it -- the payload is base64(json), so
        # anything written here is readable by anyone holding the cookie.
        # An Emby admin token grants control of the whole Emby server,
        # far beyond this app, so it must never be in a client-readable
        # container. See admin_session_store.py.
        old_handle = request.session.get("admin_session")
        if old_handle:
            admin_session_store.revoke(old_handle)
        # Scrub the pre-fix keys. An admin upgrading with an existing
        # cookie still carries a readable token in it; the session dict
        # is rewritten wholesale on response, so popping here is what
        # actually removes it from the browser.
        for _legacy in ("admin_emby_token", "admin_emby_user_id",
                        "admin_emby_is_admin"):
            request.session.pop(_legacy, None)
        request.session["admin_session"] = admin_session_store.create(
            access_token=access_token,
            user_id=user_id,
            username=request.session["admin_username"],
            is_admin=True,
        )
        logger.info(f"Admin login: '{request.session['admin_username']}'")
        return {"success": True}

    except http_requests.exceptions.Timeout:
        return {"success": False, "message": "Emby server connection timed out"}
    except http_requests.exceptions.RequestException as e:
        logger.error(f"Admin login error: {e}")
        return {"success": False, "message": "Unable to connect to Emby server"}


@router.post("/logout", response_model=SuccessResponse)
def admin_logout(request: Request,
                 admin_session_store=Depends(get_admin_session_store)):
    """Clear the standalone admin session.

    Does NOT touch host status -- a host who is also admin via Emby
    policy stays admin as long as they remain host.
    """
    # Drop the server-side credentials too, not just the cookie's handle,
    # so logout actually destroys the stashed Emby token rather than
    # merely forgetting where it lives.
    admin_session_store.revoke(request.session.get("admin_session"))
    request.session.pop("admin_authenticated", None)
    request.session.pop("admin_username", None)
    request.session.pop("admin_session", None)
    # Legacy keys from before the token moved server-side. Popped so an
    # upgrade does not leave a readable token sitting in an old cookie.
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
    body: ConfigUpdateRequest,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
    token_manager=Depends(get_token_manager),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
):
    if not is_admin_authenticated(request, party_manager):
        return ConfigUpdateResponse(success=False)

    # ConfigUpdateRequest allows extra fields (the runtime key set is
    # driven by RuntimeConfig, not a fixed schema), so flatten to a dict
    # for downstream validation. Passing `exclude_unset=True` keeps the
    # env-only guard from tripping on defaulted-but-absent keys.
    payload = body.model_dump(exclude_unset=True)

    env_only = {
        'WATCH_PARTY_BIND', 'WATCH_PARTY_PORT', 'APP_PREFIX',
        'SESSION_EXPIRY',
        'EMBY_SERVER_URL', 'EMBY_API_KEY',
    }
    env_only_hit = [k for k in payload.keys() if k in env_only]
    if env_only_hit:
        return ConfigUpdateResponse(success=False)

    try:
        changed, rejected = config.update_runtime(payload)

        if {'LOG_LEVEL', 'CONSOLE_LOG_LEVEL'} & set(changed):
            apply_log_levels(config)
            logger.info(
                f"Log levels reloaded: app={config.LOG_LEVEL}, "
                f"console={config.CONSOLE_LOG_LEVEL}"
            )

        # File-logging settings can be tuned via the admin panel but the
        # underlying handlers were only built once at boot. Flag these
        # so the UI can show a "restart required" banner instead of
        # silently pretending the change took effect.
        _RESTART_REQUIRED = {'LOG_TO_FILE', 'LOG_FILE', 'LOG_FORMAT',
                             'LOG_MAX_SIZE',
                             'ENABLE_RATE_LIMITING',
                             'RATE_LIMIT_PARTY_CREATION',
                             'RATE_LIMIT_API_CALLS'}
        restart_required = sorted(set(changed) & _RESTART_REQUIRED)

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
                # Off: cancel any countdown + force-clear the per-party
                # active flag on parties that had it armed, THEN
                # broadcast available=false to every active party. The
                # "only affected" optimisation used to skip parties
                # where the host hadn't clicked the pill, which meant
                # those parties kept rendering the button until reload
                # (contradicting the admin-panel hint). Broadcasting to
                # everyone is cheap and matches the "on" branch's shape.
                party_manager.disable_binge_watch_globally()
                for pid in party_manager.get_all().keys():
                    try:
                        await sio.emit("binge_watch_state_changed", {
                            "available": False, "active": False,
                        }, room=pid)
                    except Exception as e:
                        logger.warning(
                            f"Failed to emit binge_watch_state_changed to {pid}: {e}"
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
        logger.error(f"Config update failed: {e}")
        return ConfigUpdateResponse(success=False)


