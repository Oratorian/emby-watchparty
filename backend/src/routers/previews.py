"""Authenticated title-preview leases and an isolated opaque HLS proxy."""

from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import Field

from backend.src.dependencies import (
    PARTY_UNLOCKED_RESPONSES,
    PartySession,
    get_config,
    get_logger,
    get_media_server,
    get_preview_manager,
    require_party_unlocked,
)
from backend.src.preview_manager import (
    PREVIEW_SECONDS,
    PREVIEW_TTL_SECONDS,
    PreviewCapacityError,
    PreviewUnavailableError,
)
from backend.src.providers.models import PlaybackPlanError, UnsafeProviderResourceError
from backend.src.rate_limit import RATE_LIMIT_RESPONSES
from backend.src.routers.hls import (
    _PLAYLIST_CONTENT,
    _RANGE_RESPONSES,
    _SEGMENT_CONTENT,
    _head_responses,
)
from backend.src.schemas import HTTPErrorResponse
from backend.src.v2_schemas import V2Model

router = APIRouter(prefix="/api/v2", tags=["previews"], responses=RATE_LIMIT_RESPONSES)
_ERRORS = {
    **PARTY_UNLOCKED_RESPONSES,
    404: {"model": HTTPErrorResponse, "description": "Preview unavailable"},
    502: {"model": HTTPErrorResponse, "description": "Media server unavailable"},
}


class ShowPreviewResponseV2(V2Model):
    preview_id: str
    url: str
    duration_seconds: float = Field(gt=0, le=PREVIEW_SECONDS)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    expires_in: int = Field(gt=0, le=PREVIEW_TTL_SECONDS)


@router.post(
    "/items/{item_id}/preview",
    status_code=201,
    response_model=ShowPreviewResponseV2,
    responses={
        **_ERRORS,
        503: {"model": HTTPErrorResponse, "description": "Preview capacity reached"},
    },
)
async def create_show_preview(
    item_id: str,
    request: Request,
    session: PartySession = Depends(require_party_unlocked),
    manager=Depends(get_preview_manager),
    config=Depends(get_config),
):
    try:
        preview = await manager.create(session.party_id, session.client_id, item_id)
    except PreviewCapacityError as exc:
        raise HTTPException(503, "Preview capacity reached", headers={"Retry-After": "2"}) from exc
    except PreviewUnavailableError as exc:
        raise HTTPException(404, "Preview unavailable") from exc
    except (TimeoutError, httpx.HTTPError, PlaybackPlanError, ValueError, KeyError) as exc:
        raise HTTPException(502, "Media server unavailable") from exc
    try:
        disconnected = await request.is_disconnected()
    except BaseException:
        await manager.stop(preview.preview_id, session.party_id, session.client_id)
        raise
    if disconnected:
        await manager.stop(preview.preview_id, session.party_id, session.client_id)
        raise HTTPException(404, "Preview unavailable")
    return ShowPreviewResponseV2(
        preview_id=preview.preview_id,
        url=(
            f"{config.APP_PREFIX}/api/v2/previews/{quote(preview.preview_id, safe='')}/master.m3u8"
            f"?token={quote(preview.token, safe='')}"
        ),
        duration_seconds=PREVIEW_SECONDS,
        start_seconds=preview.start_seconds,
        expires_in=PREVIEW_TTL_SECONDS,
    )


@router.delete("/previews/{preview_id}", status_code=204, responses=PARTY_UNLOCKED_RESPONSES)
async def stop_show_preview(
    preview_id: str,
    session: PartySession = Depends(require_party_unlocked),
    manager=Depends(get_preview_manager),
):
    await manager.stop(preview_id, session.party_id, session.client_id)
    return Response(status_code=204)


@router.head(
    "/previews/{preview_id}/master.m3u8",
    response_class=Response,
    responses=_head_responses({**RATE_LIMIT_RESPONSES, **_ERRORS}),
)
@router.get(
    "/previews/{preview_id}/master.m3u8",
    response_class=Response,
    responses={
        **_ERRORS,
        200: {"content": _PLAYLIST_CONTENT, "description": "Preview HLS playlist"},
    },
)
@router.head(
    "/previews/{preview_id}/resources/{resource_id}",
    response_class=Response,
    responses=_head_responses({**RATE_LIMIT_RESPONSES, **_ERRORS, **_RANGE_RESPONSES}),
)
@router.get(
    "/previews/{preview_id}/resources/{resource_id}",
    response_class=Response,
    responses={
        **_ERRORS,
        **_RANGE_RESPONSES,
        200: {
            "content": {**_PLAYLIST_CONTENT, **_SEGMENT_CONTENT},
            "description": "Preview HLS resource",
        },
    },
)
async def preview_resource(
    preview_id: str,
    request: Request,
    resource_id: str | None = None,
    token: str = Query(min_length=1, max_length=256),
    session: PartySession = Depends(require_party_unlocked),
    manager=Depends(get_preview_manager),
    provider=Depends(get_media_server),
    config=Depends(get_config),
    logger=Depends(get_logger),
):
    preview = await manager.authorize(preview_id, session.party_id, session.client_id, token)
    if preview is None or preview.plan is None:
        raise HTTPException(404, "Preview unavailable")
    plan = preview.plan
    resource = manager.registry.resolve(preview_id, resource_id) if resource_id else plan.master
    if resource is None:
        raise HTTPException(404, "Preview unavailable")
    playlist = resource_id is None or urlsplit(resource.url).path.lower().endswith(".m3u8")
    streaming = not playlist and request.method == "GET"
    upstream = None
    try:
        if streaming:
            upstream = await manager.run_request(
                preview,
                lambda: provider.open_hls_resource(
                    plan, resource, range_header=request.headers.get("range")
                ),
            )
        else:
            upstream = await manager.run_request(
                preview,
                lambda: provider.fetch_hls_resource(
                    plan,
                    resource,
                    range_header=request.headers.get("range"),
                    head=request.method == "HEAD",
                ),
            )
        if upstream.is_redirect:
            raise ValueError("Preview redirect refused")
        headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
        for name in ("Content-Range", "Accept-Ranges", "Content-Length"):
            if value := upstream.headers.get(name):
                headers[name] = value
        if upstream.status_code == 416:
            await manager.close_response(preview, upstream)
            return Response(status_code=416, headers=headers)
        upstream.raise_for_status()
        if request.method == "HEAD":
            await manager.close_response(preview, upstream)
            return Response(status_code=upstream.status_code, headers=headers)
        if streaming:

            async def body():
                try:
                    async for chunk in upstream.aiter_bytes():
                        if preview.cancelled:
                            break
                        yield chunk
                except BaseException:
                    await manager.stop(preview.preview_id, session.party_id, session.client_id)
                    raise
                finally:
                    await manager.close_response(preview, upstream)

            return StreamingResponse(
                body(),
                status_code=upstream.status_code,
                media_type="video/MP2T"
                if urlsplit(resource.url).path.lower().endswith(".ts")
                else "application/octet-stream",
                headers=headers,
            )
        if len(upstream.content) > 1024 * 1024 or not upstream.text.lstrip().startswith("#EXTM3U"):
            raise ValueError("Invalid preview playlist")
        content = manager.registry.rewrite_playlist(
            plan,
            resource,
            upstream.text,
            resolve=lambda parent, uri: provider.resolve_hls_resource(plan, parent, uri),
            app_prefix=config.APP_PREFIX,
            token=token,
            path_prefix="/api/v2/previews",
        )
        await manager.close_response(preview, upstream)
        return Response(
            content=content,
            media_type="application/vnd.apple.mpegurl",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        )
    except PreviewUnavailableError as exc:
        if upstream is not None:
            await manager.close_response(preview, upstream)
        await manager.stop(preview.preview_id, session.party_id, session.client_id)
        raise HTTPException(404, "Preview unavailable") from exc
    except (ValueError, httpx.HTTPError, KeyError, UnsafeProviderResourceError) as exc:
        if upstream is not None:
            await manager.close_response(preview, upstream)
        await manager.stop(preview.preview_id, session.party_id, session.client_id)
        logger.warning("Preview proxy failed: error=%s", type(exc).__name__)
        raise HTTPException(502, "Preview unavailable") from exc
