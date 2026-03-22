"""
HLS Router - Proxy HLS playlists and segments from Emby
"""

import re
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
import httpx

from backend.src.dependencies import get_config, get_emby_client, get_token_manager, get_party_manager, get_logger

router = APIRouter(prefix="/hls", tags=["hls"])


def _validate_token(request: Request, config, token_manager, party_manager, logger, item_id=None):
    """Validate HLS token if enabled. Returns True if valid or validation disabled."""
    if not config.ENABLE_HLS_TOKEN_VALIDATION:
        return True
    token = request.query_params.get("token")
    if not token:
        logger.debug("Token validation failed: No token provided")
        return False
    return token_manager.validate(
        token,
        party_exists_fn=party_manager.exists,
        user_in_party_fn=lambda pid, sid: (
            party_manager.get(pid) is not None and sid in party_manager.get(pid)["users"]
        ),
    )


def _rewrite_playlist(content: str, item_id: str, app_prefix: str, emby_url: str, token: str = None):
    """Rewrite Emby URLs in HLS playlists to proxy URLs"""
    escaped_id = re.escape(item_id)

    # Replace absolute Emby URLs
    content = re.sub(
        rf"{re.escape(emby_url)}/emby/Videos/{escaped_id}/",
        f"{app_prefix}/hls/{item_id}/",
        content,
    )
    # Replace relative URLs
    content = re.sub(
        rf"/emby/Videos/{escaped_id}/",
        f"{app_prefix}/hls/{item_id}/",
        content,
    )

    # Add token to segment URLs
    if token:
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("#") or not line.strip():
                continue
            if (".m3u8" in line or ".ts" in line) and "token=" not in line:
                sep = "&" if "?" in line else "?"
                lines[i] = line + f"{sep}token={token}"
        content = "\n".join(lines)

    return content


@router.get("/{item_id}/master.m3u8")
def proxy_hls_master(item_id: str, request: Request,
                     config=Depends(get_config), emby_client=Depends(get_emby_client),
                     token_manager=Depends(get_token_manager),
                     party_manager=Depends(get_party_manager),
                     logger=Depends(get_logger)):
    emby_url = None
    try:
        if not _validate_token(request, config, token_manager, party_manager, logger, item_id):
            return Response(content='{"error": "Unauthorized"}', status_code=401,
                            media_type="application/json")

        # Build Emby URL with all query params except token
        query_params = {k: v for k, v in request.query_params.items() if k != "token"}
        query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
        emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/master.m3u8"
        if query_string:
            emby_url += f"?{query_string}"

        logger.debug(f"Proxying HLS master: {emby_url}")
        emby_resp = httpx.get(emby_url, headers=emby_client.headers)
        emby_resp.raise_for_status()

        token = request.query_params.get("token") if config.ENABLE_HLS_TOKEN_VALIDATION else None
        playlist = _rewrite_playlist(
            emby_resp.text, item_id, config.APP_PREFIX, config.EMBY_SERVER_URL, token
        )

        return Response(
            content=playlist,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Access-Control-Allow-Origin": "*",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch master playlist: {e}")
        return Response(content='{"error": "Failed to fetch video from media server"}',
                        status_code=502, media_type="application/json")
    except Exception as e:
        logger.error(f"Unexpected error in HLS master proxy: {e}")
        return Response(content='{"error": "Internal server error"}',
                        status_code=500, media_type="application/json")


@router.get("/{item_id}/{subpath:path}")
def proxy_hls_segment(item_id: str, subpath: str, request: Request,
                      config=Depends(get_config), emby_client=Depends(get_emby_client),
                      token_manager=Depends(get_token_manager),
                      party_manager=Depends(get_party_manager),
                      logger=Depends(get_logger)):
    emby_url = None
    try:
        if not _validate_token(request, config, token_manager, party_manager, logger, item_id):
            return Response(content='{"error": "Unauthorized"}', status_code=401,
                            media_type="application/json")

        query_params = {k: v for k, v in request.query_params.items() if k != "token"}
        query_string = "&".join(f"{k}={v}" for k, v in query_params.items())
        emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{subpath}"
        if query_string:
            emby_url += f"?{query_string}"

        logger.debug(f"Proxying HLS segment: {subpath} -> {emby_url}")

        # For playlists, fetch and rewrite
        if subpath.endswith(".m3u8"):
            emby_resp = httpx.get(emby_url, headers=emby_client.headers)
            emby_resp.raise_for_status()
            token = request.query_params.get("token") if config.ENABLE_HLS_TOKEN_VALIDATION else None
            playlist = _rewrite_playlist(
                emby_resp.text, item_id, config.APP_PREFIX, config.EMBY_SERVER_URL, token
            )
            return Response(
                content=playlist,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        # For segments, stream through
        emby_resp = httpx.get(emby_url, headers=emby_client.headers)
        emby_resp.raise_for_status()

        content_type = "video/MP2T" if subpath.endswith(".ts") else "application/octet-stream"

        return Response(
            content=emby_resp.content,
            media_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "X-Content-Type-Options": "nosniff",
                "Content-Length": str(len(emby_resp.content)),
            },
        )

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch HLS segment {subpath}: {e}")
        return Response(content='{"error": "Failed to fetch segment"}',
                        status_code=502, media_type="application/json")
    except Exception as e:
        logger.error(f"Unexpected error in HLS segment proxy: {e}")
        return Response(content='{"error": "Internal server error"}',
                        status_code=500, media_type="application/json")
