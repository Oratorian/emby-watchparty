"""
HLS Router - Proxy HLS playlists and segments from Emby.

Auth model: the URL-embedded HLS token (HLSTokenManager) proves the
caller is a member of the party. The party's host_access_token is then
used to sign every upstream Emby request. When the host fully leaves
(token cleared) the route returns 423 -- but during PLAYING-ONLY the
stored token keeps the current video alive until it ends naturally.
"""

import re
from urllib.parse import unquote, urlsplit
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
import httpx

from backend.src.dependencies import (
    get_config, get_emby_client, get_emby_gateway, get_token_manager,
    get_party_manager, get_logger,
)

router = APIRouter(prefix="/hls", tags=["hls"])


# Upstream Emby HTTP timeout. Without an explicit bound, a slow or
# misbehaving Emby can pin uvicorn worker slots until the OS TCP
# timeout, exhausting the thread pool for everyone. Enough for a large
# segment on a fresh transcode; a healthy Emby returns segments in
# well under this.
_EMBY_HTTP_TIMEOUT = 30.0


# Allowlist of query params that legitimately flow from client -> Emby.
# The old passthrough (`{k: v for k, v in query_params if k != 'token'}`)
# let a caller with a valid HLS token supply arbitrary Emby params
# (including `api_key=`, `Static=true`, `redirect=`) which some Emby
# versions honor and which could bypass the intended transcode
# configuration. This set is the concrete list of names StreamBuilder
# and the frontend can emit.
_ALLOWED_EMBY_PARAMS = {
    "MediaSourceId", "PlaySessionId", "DeviceId",
    "SegmentContainer", "TranscodingMaxAudioChannels", "AudioCodec",
    "AudioBitrate", "BreakOnNonKeyFrames", "MaxAudioChannels",
    "MinSegments", "h264-profile", "h264-level", "VideoCodec",
    "MaxWidth", "MaxHeight", "TranscodeReasons",
    "EnableAutoStreamCopy", "VideoBitrate",
    "AudioStreamIndex", "SubtitleStreamIndex", "SubtitleMethod",
    "StartTimeTicks",
}


class UnsafeHLSQuery(ValueError):
    """A client supplied a parameter outside the HLS allowlist."""


def _sanitize_query(query_items):
    """Remove the party token and reject every unapproved upstream parameter."""
    sanitized = []
    for key, value in query_items:
        if key == "token":
            continue
        if key not in _ALLOWED_EMBY_PARAMS:
            raise UnsafeHLSQuery(key)
        sanitized.append((key, value))
    return sanitized


def _safe_hls_subpath(subpath: str) -> bool:
    decoded = subpath
    for _ in range(8):
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    else:
        return False
    parsed = urlsplit(decoded)
    if (
        not decoded
        or parsed.scheme
        or parsed.netloc
        or decoded.startswith(('/', '\\'))
    ):
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        return False
    normalized = decoded.replace('\\', '/')
    return not any(part in {'.', '..'} for part in normalized.split('/'))


def _resolve_host_creds(request: Request, token_manager, party_manager, logger):
    """Validate the HLS token and return (host_access_token, host_user_id, party_id).

    Returns (None, None, None) when validation or host lookup fails so
    the caller can render the right HTTP error.
    """
    token = request.query_params.get("token")
    if not token:
        logger.debug("HLS denied: no token")
        return None, None, None

    party_id = token_manager.get_party_id(token)
    if not party_id:
        logger.debug("HLS denied: token unknown or expired")
        return None, None, None

    valid = token_manager.validate(
        token,
        party_exists_fn=party_manager.exists,
        user_in_party_fn=lambda pid, sid: (
            party_manager.get(pid) is not None
            and party_manager.get(pid).has_sid(sid)
        ),
    )
    if not valid:
        logger.debug(f"HLS denied: token failed validation for party {party_id}")
        return None, None, None

    party = party_manager.get(party_id)
    if not party or not party.host_access_token:
        logger.debug(f"HLS denied: party {party_id} has no host token")
        return None, None, None

    return party.host_access_token, party.host_user_id, party_id


def _rewrite_playlist(
    content: str,
    item_id: str,
    app_prefix: str,
    emby_url: str,
    token: str | None = None,
) -> str:
    """Rewrite Emby URLs in HLS playlists to proxy URLs"""
    escaped_id = re.escape(item_id)

    content = re.sub(
        rf"{re.escape(emby_url)}/emby/Videos/{escaped_id}/",
        f"{app_prefix}/hls/{item_id}/",
        content,
    )
    content = re.sub(
        rf"/emby/Videos/{escaped_id}/",
        f"{app_prefix}/hls/{item_id}/",
        content,
    )

    if token:
        # Emby emits CRLF playlists. Keep each terminator so the token is
        # inserted before it and the upstream playlist formatting remains
        # unchanged. Appending after "\r" makes HLS.js parse the token as
        # a separate, invalid line.
        lines = content.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.strip().startswith("#") or not line.strip():
                continue
            uri = line.rstrip("\r\n")
            terminator = line[len(uri):]
            parsed = urlsplit(uri)
            if parsed.scheme or parsed.netloc or uri.startswith(("/", "\\")):
                raise ValueError("playlist contains an unsafe absolute URI")
            if (".m3u8" in uri or ".ts" in uri) and "token=" not in uri:
                sep = "&" if "?" in uri else "?"
                lines[i] = uri + f"{sep}token={token}" + terminator
        content = "".join(lines)

    return content


@router.get(
    "/{item_id}/master.m3u8",
    responses={
        200: {
            "content": {"application/vnd.apple.mpegurl": {}},
            "description": "HLS master playlist (rewritten to proxy URLs)",
        },
        401: {"description": "HLS token missing, invalid, or party has no host"},
        500: {"description": "Internal proxy error"},
        502: {"description": "Upstream Emby request failed"},
    },
)
async def proxy_hls_master(item_id: str, request: Request,
                     config=Depends(get_config), emby_client=Depends(get_emby_client),
                     emby_gateway=Depends(get_emby_gateway),
                     token_manager=Depends(get_token_manager),
                     party_manager=Depends(get_party_manager),
                     logger=Depends(get_logger)):
    try:
        access_token, user_id, _ = _resolve_host_creds(
            request, token_manager, party_manager, logger
        )
        if not access_token:
            return Response(
                content='{"error": "Unauthorized"}', status_code=401,
                media_type="application/json",
            )

        query_params = _sanitize_query(request.query_params.multi_items())
        emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/master.m3u8"

        logger.debug(f"Proxying HLS master: {emby_url}")
        emby_resp = await emby_gateway.get(
            emby_url,
            headers=emby_client._headers(access_token, user_id),
            params=query_params,
            timeout=_EMBY_HTTP_TIMEOUT,
        )
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
    except UnsafeHLSQuery as e:
        logger.warning("Rejected unapproved HLS query parameter: %s", e)
        return Response(
            content='{"error": "Invalid HLS query"}',
            status_code=400,
            media_type="application/json",
        )
    except ValueError as e:
        logger.warning(f"Rejected unsafe master playlist: {e}")
        return Response(content='{"error": "Unsafe upstream playlist"}',
                        status_code=502, media_type="application/json")
    except httpx.HTTPError as e:
        logger.error("Failed to fetch master playlist: error=%s", type(e).__name__)
        return Response(content='{"error": "Failed to fetch video from media server"}',
                        status_code=502, media_type="application/json")
    except Exception as e:
        logger.error("Unexpected HLS master proxy error=%s", type(e).__name__)
        return Response(content='{"error": "Internal server error"}',
                        status_code=500, media_type="application/json")


@router.get(
    "/{item_id}/{subpath:path}",
    responses={
        200: {
            "content": {
                "application/vnd.apple.mpegurl": {},
                "video/MP2T": {},
                "application/octet-stream": {},
            },
            "description": "HLS variant playlist or .ts segment",
        },
        401: {"description": "HLS token missing, invalid, or party has no host"},
        500: {"description": "Internal proxy error"},
        502: {"description": "Upstream Emby request failed"},
    },
)
async def proxy_hls_segment(item_id: str, subpath: str, request: Request,
                      config=Depends(get_config), emby_client=Depends(get_emby_client),
                      emby_gateway=Depends(get_emby_gateway),
                      token_manager=Depends(get_token_manager),
                      party_manager=Depends(get_party_manager),
                      logger=Depends(get_logger)):
    try:
        if not _safe_hls_subpath(subpath):
            return Response(
                content='{"error": "Invalid HLS path"}',
                status_code=400,
                media_type="application/json",
            )
        access_token, user_id, _ = _resolve_host_creds(
            request, token_manager, party_manager, logger
        )
        if not access_token:
            return Response(
                content='{"error": "Unauthorized"}', status_code=401,
                media_type="application/json",
            )

        query_params = _sanitize_query(request.query_params.multi_items())
        emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{subpath}"

        logger.debug(f"Proxying HLS segment: {subpath} -> {emby_url}")

        if subpath.endswith(".m3u8"):
            emby_resp = await emby_gateway.get(
                emby_url,
                headers=emby_client._headers(access_token, user_id),
                params=query_params,
                timeout=_EMBY_HTTP_TIMEOUT,
            )
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

        upstream_headers = emby_client._headers(access_token, user_id)
        if range_header := request.headers.get("range"):
            upstream_headers["Range"] = range_header
        emby_resp = await emby_gateway.open_stream(
            emby_url,
            headers=upstream_headers,
            params=query_params,
        )
        try:
            emby_resp.raise_for_status()
        except Exception:
            await emby_resp.aclose()
            raise

        content_type = "video/MP2T" if subpath.endswith(".ts") else "application/octet-stream"

        async def stream_body():
            try:
                async for chunk in emby_resp.aiter_bytes():
                    yield chunk
            finally:
                await emby_resp.aclose()

        response_headers = {
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        }
        if emby_resp.status_code == 206:
            for header in ("Content-Range", "Accept-Ranges", "Content-Length"):
                if value := emby_resp.headers.get(header):
                    response_headers[header] = value

        return StreamingResponse(
            stream_body(),
            status_code=emby_resp.status_code,
            media_type=content_type,
            headers=response_headers,
        )

    except UnsafeHLSQuery as e:
        logger.warning("Rejected unapproved HLS query parameter: %s", e)
        return Response(
            content='{"error": "Invalid HLS query"}',
            status_code=400,
            media_type="application/json",
        )
    except ValueError as e:
        logger.warning(f"Rejected unsafe HLS playlist {subpath}: {e}")
        return Response(content='{"error": "Unsafe upstream playlist"}',
                        status_code=502, media_type="application/json")
    except httpx.HTTPError as e:
        logger.error(
            "Failed to fetch HLS segment path=%s error=%s",
            subpath,
            type(e).__name__,
        )
        return Response(content='{"error": "Failed to fetch segment"}',
                        status_code=502, media_type="application/json")
    except Exception as e:
        logger.error("Unexpected HLS segment proxy error=%s", type(e).__name__)
        return Response(content='{"error": "Internal server error"}',
                        status_code=500, media_type="application/json")
