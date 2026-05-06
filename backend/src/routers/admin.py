"""
Admin Router - Settings management
Requires Emby administrator credentials
"""

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
import requests as http_requests

from backend.src.dependencies import get_config, get_emby_client, get_logger, get_party_manager
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
        is_admin = data.get("User", {}).get("Policy", {}).get("IsAdministrator", False)

        if not is_admin:
            logger.warning(f"Admin login denied for '{body.username}' -- not administrator")
            return {"success": False, "message": "This account does not have administrator privileges"}

        request.session["admin_authenticated"] = True
        request.session["admin_username"] = data.get("User", {}).get("Name", body.username)
        logger.info(f"Admin login: '{request.session['admin_username']}'")
        return {"success": True}

    except http_requests.exceptions.Timeout:
        return {"success": False, "message": "Emby server connection timed out"}
    except http_requests.exceptions.RequestException as e:
        logger.error(f"Admin login error: {e}")
        return {"success": False, "message": "Unable to connect to Emby server"}


@router.post("/logout", response_model=SuccessResponse)
def admin_logout(request: Request):
    request.session.pop("admin_authenticated", None)
    request.session.pop("admin_username", None)
    return {"success": True}


@router.get("/config", response_model=RuntimeConfigResponse)
def get_config_values(request: Request, config=Depends(get_config)):
    if not request.session.get("admin_authenticated"):
        return {"error": "Not authenticated"}
    return config.get_runtime_dict()


@router.put("/config", response_model=ConfigUpdateResponse)
def update_config(request: Request, body: dict, config=Depends(get_config),
                  party_manager=Depends(get_party_manager),
                  logger=Depends(get_logger)):
    if not request.session.get("admin_authenticated"):
        return ConfigUpdateResponse(success=False)

    env_only = {
        'WATCH_PARTY_BIND', 'WATCH_PARTY_PORT', 'APP_PREFIX',
        'REQUIRE_LOGIN', 'SESSION_EXPIRY',
        'EMBY_SERVER_URL', 'EMBY_API_KEY', 'EMBY_USERNAME', 'EMBY_PASSWORD',
    }
    rejected = [k for k in body.keys() if k in env_only]
    if rejected:
        return ConfigUpdateResponse(success=False)

    try:
        changed = config.update_runtime(body)

        if {'LOG_LEVEL', 'CONSOLE_LOG_LEVEL'} & set(changed):
            _reload_log_levels(config, logger)

        # Static session toggles or id renames need an explicit sync
        # because the static party lives in PartyManager.watch_parties,
        # not in the config object. Without this, enabling static
        # sessions via the admin panel would persist the setting but
        # never actually create the party until restart.
        if {'STATIC_SESSION_ENABLED', 'STATIC_SESSION_ID'} & set(changed):
            party_manager.sync_static_party()

        logger.info(f"Admin config updated: {changed}")
        return ConfigUpdateResponse(success=True, changed=changed, config=config.get_runtime_dict())
    except Exception as e:
        logger.error(f"Config update failed: {e}")
        return ConfigUpdateResponse(success=False)


def _reload_log_levels(config, logger):
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    console_level = getattr(logging, config.CONSOLE_LOG_LEVEL.upper(), logging.WARNING)
    for name in ['emby-watchparty', 'socketio', 'uvicorn']:
        lg = logging.getLogger(name)
        lg.setLevel(level)
        for handler in lg.handlers:
            if hasattr(handler, 'stream') and hasattr(handler.stream, 'isatty'):
                handler.setLevel(console_level)
            else:
                handler.setLevel(level)
    logger.info(f"Log levels reloaded: app={config.LOG_LEVEL}, console={config.CONSOLE_LOG_LEVEL}")
