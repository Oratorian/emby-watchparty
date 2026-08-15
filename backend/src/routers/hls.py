"""
HLS Router - Proxy HLS playlists and segments from Emby.

Auth model: the signed cookie resolves the caller's active party. With
validation enabled, the URL token must be valid for that same party.
The party's host_access_token signs every upstream Emby request. When the host fully leaves
(token cleared) the route returns 423 -- but during PLAYING-ONLY the
stored token keeps the current video alive until it ends naturally.
"""

import re
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from backend.src.dependencies import (
    PARTY_HOST_TOKEN_RESPONSES,
    PartySession,
    get_config,
    get_emby_client,
    get_emby_gateway,
    get_hls_registry,
    get_logger,
    get_media_server,
    get_party_manager,
    get_token_manager,
    require_host_token,
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
    "MediaSourceId",
    "PlaySessionId",
    "DeviceId",
    "SegmentContainer",
    "TranscodingMaxAudioChannels",
    "AudioCodec",
    "AudioBitrate",
    "BreakOnNonKeyFrames",
    "MaxAudioChannels",
    "MinSegments",
    "h264-profile",
    "h264-level",
    "VideoCodec",
    "MaxWidth",
    "MaxHeight",
    "TranscodeReasons",
    "EnableAutoStreamCopy",
    "VideoBitrate",
    "AudioStreamIndex",
    "SubtitleStreamIndex",
    "SubtitleMethod",
    "StartTimeTicks",
}


class UnsafeHLSQueryError(ValueError):
    """A client supplied a parameter outside the HLS allowlist."""


def _sanitize_query(query_items, *, strict: bool, logger=None):
    """Remove the party token and hold every other parameter to the allowlist.

    `strict` decides what an unapproved name costs, and the two callers
    differ in who authored the query.

    The master request is built by our own StreamBuilder, so the allowlist
    is the exact vocabulary it emits. Anything else there was appended by
    the caller, which is the tampering this guard exists to stop, and
    refusing it outright is both safe and loud.

    Variant and segment URLs are Emby's. `_rewrite_playlist` rewrites the
    path and leaves the query intact, so whatever Emby put in its playlist
    round-trips through the client and arrives here. That vocabulary is
    Emby's to change and is not enumerable from this side, so a name we do
    not recognise is far more likely to be a version difference than an
    attack. Rejecting cost the viewer all playback; dropping costs at most
    one parameter, and the parameter still never reaches Emby, so the
    security property is unchanged either way.
    """
    sanitized = []
    dropped = []
    for key, value in query_items:
        if key == "token":
            continue
        if key not in _ALLOWED_EMBY_PARAMS:
            if strict:
                raise UnsafeHLSQueryError(key)
            dropped.append(key)
            continue
        sanitized.append((key, value))
    if dropped and logger:
        logger.debug("Dropped unapproved HLS query parameters: %s", ", ".join(sorted(set(dropped))))
    return sanitized


def _is_playlist(value: str) -> bool:
    """Whether `value` names an HLS playlist, regardless of case.

    Nothing constrains the case of a requested subpath: `_safe_hls_subpath`
    rejects traversal and control characters but never inspects the
    extension. A case-sensitive test therefore let `variant.M3U8` miss the
    playlist branch and fall through to the segment streamer, which handed
    the raw upstream body back unrewritten, unvalidated, and without a
    token appended to its child URIs.
    """
    return value.lower().endswith(".m3u8")


def _is_segment(value: str) -> bool:
    """Whether `value` names a transport-stream segment, regardless of case."""
    return value.lower().endswith(".ts")


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
    if not decoded or parsed.scheme or parsed.netloc or decoded.startswith(("/", "\\")):
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        return False
    normalized = decoded.replace("\\", "/")
    return not any(part in {".", ".."} for part in normalized.split("/"))


def _resolve_host_creds(
    request: Request,
    config,
    token_manager,
    party_manager,
    logger,
    *,
    session_party_id: str,
):
    """Authorize through token or dev session; return host credentials and party ID.

    Returns (None, None, None) when validation or host lookup fails so
    the caller can render the right HTTP error.
    """
    if config.ENABLE_HLS_TOKEN_VALIDATION:
        token = request.query_params.get("token")
        if not token:
            logger.debug("HLS denied: no token")
            return None, None, None

        party_id = token_manager.get_party_id(token)
        if not party_id:
            logger.debug("HLS denied: token unknown or expired")
            return None, None, None

        if party_id.upper() != session_party_id.upper():
            logger.warning(
                "HLS denied: token party %s does not match session party %s",
                party_id,
                session_party_id,
            )
            return None, None, None

        valid = token_manager.validate(
            token,
            party_exists_fn=party_manager.exists,
            user_in_party_fn=lambda pid, sid: (
                party_manager.get(pid) is not None and party_manager.get(pid).has_sid(sid)
            ),
        )
        if not valid:
            logger.debug(f"HLS denied: token failed validation for party {party_id}")
            return None, None, None
    else:
        party_id = session_party_id

    party = party_manager.get(party_id)
    if not party or not party.host_access_token:
        logger.debug(f"HLS denied: party {party_id} has no host token")
        return None, None, None

    return party.host_access_token, party.host_user_id, party_id


def _safe_upstream_playlist_uri(uri: str, item_id: str, emby_url: str) -> bool:
    if any(ord(character) < 32 or ord(character) == 127 for character in uri):
        return False

    parsed = urlsplit(uri)
    emby = urlsplit(emby_url)
    upstream_path = f"{emby.path.rstrip('/')}/emby/Videos/{item_id}/"
    root_path = f"/emby/Videos/{item_id}/"

    if parsed.scheme or parsed.netloc:
        if parsed.scheme != emby.scheme or parsed.netloc != emby.netloc:
            return False
        if not parsed.path.startswith(upstream_path):
            return False
        subpath = parsed.path[len(upstream_path) :]
    elif uri.startswith(("/", "\\")):
        if not parsed.path.startswith(root_path):
            return False
        subpath = parsed.path[len(root_path) :]
    else:
        subpath = parsed.path

    return _safe_hls_subpath(subpath)


def _rewrite_playlist(
    content: str,
    item_id: str,
    app_prefix: str,
    emby_url: str,
    token: str | None = None,
) -> str:
    """Rewrite Emby URLs in HLS playlists to proxy URLs"""
    escaped_id = re.escape(item_id)

    raw_lines = content.splitlines(keepends=True)
    for line in raw_lines:
        if line.strip().startswith("#") or not line.strip():
            continue
        uri = line.rstrip("\r\n")
        if not _safe_upstream_playlist_uri(uri, item_id, emby_url):
            raise ValueError("playlist contains an unsafe URI")

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
            terminator = line[len(uri) :]
            lowered = uri.lower()
            if (".m3u8" in lowered or ".ts" in lowered) and "token=" not in lowered:
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
        **PARTY_HOST_TOKEN_RESPONSES,
        500: {"description": "Internal proxy error"},
        502: {"description": "Upstream Emby request failed"},
    },
)
async def proxy_hls_master(
    item_id: str,
    request: Request,
    party_session: PartySession = Depends(require_host_token),
    config=Depends(get_config),
    emby_client=Depends(get_emby_client),
    emby_gateway=Depends(get_emby_gateway),
    token_manager=Depends(get_token_manager),
    party_manager=Depends(get_party_manager),
    logger=Depends(get_logger),
    media_server=Depends(get_media_server),
    hls_registry=Depends(get_hls_registry),
):
    try:
        access_token, user_id, _ = _resolve_host_creds(
            request,
            config,
            token_manager,
            party_manager,
            logger,
            session_party_id=party_session.party_id,
        )
        if not access_token:
            return Response(
                content='{"error": "Unauthorized"}',
                status_code=401,
                media_type="application/json",
            )

        plan = hls_registry.get_plan(item_id)
        if plan is not None:
            token = request.query_params.get("token")
            if config.ENABLE_HLS_TOKEN_VALIDATION:
                claims = token_manager.get_claims(token or "")
                sid = claims[1] if claims else None
            else:
                sid = next(
                    (
                        candidate_sid
                        for candidate_sid, client_id in party_session.party.sid_client_ids.items()
                        if client_id == party_session.client_id
                    ),
                    None,
                )
            stream = party_session.party.user_streams.get(sid) if sid else None
            if stream is None or stream.stream_id != plan.stream_id:
                return Response(
                    content='{"error": "Unauthorized"}',
                    status_code=401,
                    media_type="application/json",
                )
            upstream = await media_server.fetch_hls_resource(plan, plan.master)
            if upstream.is_redirect:
                logger.warning("Media server redirected an HLS master request; not followed")
                return Response(
                    content='{"error": "Upstream redirect not followed"}',
                    status_code=502,
                    media_type="application/json",
                )
            upstream.raise_for_status()
            playlist = hls_registry.rewrite_playlist(
                plan,
                plan.master,
                upstream.text,
                resolve=lambda parent, uri: media_server.resolve_hls_resource(plan, parent, uri),
                app_prefix=config.APP_PREFIX,
                token=token or "",
            )
            return Response(
                content=playlist,
                media_type="application/vnd.apple.mpegurl",
                headers={"X-Content-Type-Options": "nosniff"},
            )

        query_params = _sanitize_query(request.query_params.multi_items(), strict=True)
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
                "X-Content-Type-Options": "nosniff",
            },
        )
    except UnsafeHLSQueryError as e:
        logger.warning("Rejected unapproved HLS query parameter: %s", e)
        return Response(
            content='{"error": "Invalid HLS query"}',
            status_code=400,
            media_type="application/json",
        )
    except ValueError as e:
        logger.warning("Rejected unsafe master playlist: error=%s", type(e).__name__)
        return Response(
            content='{"error": "Unsafe upstream playlist"}',
            status_code=502,
            media_type="application/json",
        )
    except httpx.HTTPError as e:
        logger.error("Failed to fetch master playlist: error=%s", type(e).__name__)
        return Response(
            content='{"error": "Failed to fetch video from media server"}',
            status_code=502,
            media_type="application/json",
        )
    except Exception as e:
        logger.error("Unexpected HLS master proxy error=%s", type(e).__name__)
        return Response(
            content='{"error": "Internal server error"}',
            status_code=500,
            media_type="application/json",
        )


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
        **PARTY_HOST_TOKEN_RESPONSES,
        500: {"description": "Internal proxy error"},
        502: {"description": "Upstream Emby request failed"},
    },
)
async def proxy_hls_segment(
    item_id: str,
    subpath: str,
    request: Request,
    party_session: PartySession = Depends(require_host_token),
    config=Depends(get_config),
    emby_client=Depends(get_emby_client),
    emby_gateway=Depends(get_emby_gateway),
    token_manager=Depends(get_token_manager),
    party_manager=Depends(get_party_manager),
    logger=Depends(get_logger),
):
    try:
        if not _safe_hls_subpath(subpath):
            return Response(
                content='{"error": "Invalid HLS path"}',
                status_code=400,
                media_type="application/json",
            )
        access_token, user_id, _ = _resolve_host_creds(
            request,
            config,
            token_manager,
            party_manager,
            logger,
            session_party_id=party_session.party_id,
        )
        if not access_token:
            return Response(
                content='{"error": "Unauthorized"}',
                status_code=401,
                media_type="application/json",
            )

        query_params = _sanitize_query(
            request.query_params.multi_items(), strict=False, logger=logger
        )
        emby_url = f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{subpath}"

        logger.debug(f"Proxying HLS segment: {subpath} -> {emby_url}")

        if _is_playlist(subpath):
            emby_resp = await emby_gateway.get(
                emby_url,
                headers=emby_client._headers(access_token, user_id),
                params=query_params,
                timeout=_EMBY_HTTP_TIMEOUT,
            )
            emby_resp.raise_for_status()
            token = (
                request.query_params.get("token") if config.ENABLE_HLS_TOKEN_VALIDATION else None
            )
            playlist = _rewrite_playlist(
                emby_resp.text, item_id, config.APP_PREFIX, config.EMBY_SERVER_URL, token
            )
            return Response(
                content=playlist,
                media_type="application/vnd.apple.mpegurl",
                headers={
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
        if emby_resp.status_code == 416:
            # Range Not Satisfiable is an answer, not a failure. RFC 7233
            # requires it to carry `Content-Range: bytes */<length>`, which
            # is how a client discovers the real length and retries. Letting
            # raise_for_status turn it into a generic upstream error threw
            # that header away and told the client nothing it could act on.
            content_range = emby_resp.headers.get("Content-Range", "")
            await emby_resp.aclose()
            return Response(
                status_code=416,
                headers=(
                    {"Content-Range": content_range, "X-Content-Type-Options": "nosniff"}
                    if content_range
                    else {"X-Content-Type-Options": "nosniff"}
                ),
            )

        try:
            emby_resp.raise_for_status()
        except Exception:
            await emby_resp.aclose()
            raise

        if emby_resp.is_redirect:
            # `follow_redirects=False` on the shared client is deliberate:
            # following Emby's redirect would re-issue the host's credentials
            # at whatever target it names. Forwarding it is no better, because
            # Location points at an internal address the viewer cannot reach
            # and should not be shown. Previously neither happened and the
            # viewer received a bare 3xx with no Location at all, which is
            # unactionable. Fail it as an upstream error instead.
            await emby_resp.aclose()
            logger.warning(
                "Emby redirected an HLS segment request; not followed: status=%s",
                emby_resp.status_code,
            )
            return Response(
                content='{"error": "Upstream redirect not followed"}',
                status_code=502,
                media_type="application/json",
            )

        content_type = "video/MP2T" if _is_segment(subpath) else "application/octet-stream"

        async def stream_body():
            try:
                async for chunk in emby_resp.aiter_bytes():
                    yield chunk
            finally:
                await emby_resp.aclose()

        # Range metadata matters well beyond 206. A plain 200 needs
        # Content-Length and Accept-Ranges before a client will attempt to
        # seek at all, and RFC 7233 requires a 416 to carry Content-Range so
        # the client can learn the real length and retry. Copying these only
        # on 206 meant iOS, which drives native HLS entirely through range
        # requests, could neither start seeking nor recover from an
        # out-of-range one. Forward whatever upstream actually sent.
        response_headers = {
            "X-Content-Type-Options": "nosniff",
        }
        for header in ("Content-Range", "Accept-Ranges", "Content-Length"):
            if value := emby_resp.headers.get(header):
                response_headers[header] = value

        return StreamingResponse(
            stream_body(),
            status_code=emby_resp.status_code,
            media_type=content_type,
            headers=response_headers,
        )

    except UnsafeHLSQueryError as e:
        logger.warning("Rejected unapproved HLS query parameter: %s", e)
        return Response(
            content='{"error": "Invalid HLS query"}',
            status_code=400,
            media_type="application/json",
        )
    except ValueError as e:
        logger.warning(
            "Rejected unsafe HLS playlist path=%s error=%s",
            subpath,
            type(e).__name__,
        )
        return Response(
            content='{"error": "Unsafe upstream playlist"}',
            status_code=502,
            media_type="application/json",
        )
    except httpx.HTTPError as e:
        logger.error(
            "Failed to fetch HLS segment path=%s error=%s",
            subpath,
            type(e).__name__,
        )
        return Response(
            content='{"error": "Failed to fetch segment"}',
            status_code=502,
            media_type="application/json",
        )
    except Exception as e:
        logger.error("Unexpected HLS segment proxy error=%s", type(e).__name__)
        return Response(
            content='{"error": "Internal server error"}',
            status_code=500,
            media_type="application/json",
        )
