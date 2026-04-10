"""
Auth Router - Login, logout, status, version
"""

from fastapi import APIRouter, Depends, Request
import requests as http_requests

from backend.src import __version__, __codename__
from backend.src.dependencies import get_config, get_emby_client, get_logger
from backend.src.schemas import (
    LoginRequest, LoginResponse, AuthStatusResponse, VersionResponse,
)

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def api_login(body: LoginRequest, request: Request,
              config=Depends(get_config), emby_client=Depends(get_emby_client),
              logger=Depends(get_logger)):
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
            timeout=30,
        )

        if resp.status_code != 200:
            return LoginResponse(success=False, message="Invalid username or password")

        data = resp.json()
        access_token = data.get("AccessToken")
        user_name = data.get("User", {}).get("Name", body.username)
        is_admin = data.get("User", {}).get("Policy", {}).get("IsAdministrator", False)

        if not access_token:
            return LoginResponse(success=False, message="Authentication failed")

        request.session["authenticated"] = True
        request.session["username"] = user_name
        request.session["is_admin"] = is_admin

        logger.info(f"User '{user_name}' logged in (admin={is_admin})")
        return LoginResponse(success=True, message="Login successful", username=user_name)

    except http_requests.exceptions.Timeout:
        return LoginResponse(success=False, message="Connection to Emby server timed out")
    except http_requests.exceptions.RequestException:
        return LoginResponse(success=False, message="Unable to connect to Emby server")


@router.post("/auth/logout", response_model=LoginResponse)
def api_logout(request: Request, logger=Depends(get_logger)):
    username = request.session.get("username", "Unknown")
    request.session.clear()
    logger.info(f"User '{username}' logged out")
    return {"success": True, "message": "Logged out"}


@router.get("/auth/status", response_model=AuthStatusResponse)
def api_auth_status(request: Request, config=Depends(get_config)):
    return AuthStatusResponse(
        authenticated=request.session.get("authenticated", False),
        username=request.session.get("username"),
        is_admin=request.session.get("is_admin", False),
        require_login=config.REQUIRE_LOGIN,
    )


@router.get("/version", response_model=VersionResponse)
def api_version():
    result = VersionResponse(current_version=__version__, codename=__codename__)
    try:
        url = "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
        resp = http_requests.get(url, timeout=5)
        if resp.status_code == 200:
            release = resp.json()
            latest = release.get("tag_name", "").lstrip("v")
            result.latest_version = latest
            result.update_available = bool(latest and latest != __version__)
            result.release_url = release.get("html_url")
    except Exception:
        pass
    return result
