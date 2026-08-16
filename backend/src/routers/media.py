"""Media Router - Intro info, image proxy, subtitle proxy.

`/intro` requires require_party_unlocked (the host's library is being
queried). `/image` and `/subtitles` only require require_host_token so
that the poster art and subtitles of the in-flight video keep working
during the PLAYING-ONLY state after the host leaves.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from backend.src.dependencies import (
    PARTY_HOST_TOKEN_RESPONSES,
    PARTY_UNLOCKED_RESPONSES,
    PartySession,
    get_logger,
    get_media_server,
    require_host_token,
    require_party_unlocked,
)
from backend.src.providers.models import AssetRequest, ProviderCredentials
from backend.src.schemas import IntroResponse

# These compatibility routes intentionally collapse provider failures into
# their historical no-intro / 404 responses.
router = APIRouter(prefix="/api", tags=["media"])


@router.get(
    "/intro/{item_id}",
    response_model=IntroResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def get_intro_info(
    item_id: str,
    media_server=Depends(get_media_server),
    logger=Depends(get_logger),
    party_session: PartySession = Depends(require_party_unlocked),
):
    logger.debug(f"Fetching intro info for item ID: {item_id}")
    try:
        party = party_session.party
        intro = await media_server.get_intro(
            item_id,
            ProviderCredentials(
                party.host_access_token or "",
                party.host_user_id or "",
            ),
        )
        if intro is not None:
            logger.info(
                "Found intro for %s: %.2fs - %.2fs",
                item_id,
                intro.start_seconds,
                intro.end_seconds,
            )
            return IntroResponse(
                hasIntro=True,
                start=intro.start_seconds,
                end=intro.end_seconds,
                duration=intro.end_seconds - intro.start_seconds,
            )
        return IntroResponse(hasIntro=False)
    except Exception as e:
        logger.warning("Intro fetch failed item=%s error=%s", item_id, type(e).__name__)
        return IntroResponse(hasIntro=False)


@router.get(
    "/image/{item_id}",
    responses={
        200: {
            "content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}},
            "description": "Item poster / image bytes proxied from media server",
        },
        404: {"description": "No such image"},
        **PARTY_HOST_TOKEN_RESPONSES,
    },
)
async def api_image(
    item_id: str,
    type: Literal["Primary", "Backdrop", "Logo", "Thumb", "Art", "Banner"] = Query("Primary"),
    index: int | None = Query(None, ge=0, le=99),
    # Optional sizing forwarded to media server. Library card thumbnails only
    # need ~240x360, but the original 2.0 endpoint proxied the full
    # poster bytes (often ~1000px wide / hundreds of KB) which made
    # the library card grid feel sluggish on throttled connections
    # (reported in beta12 by xyxxyxxy). With these params media server
    # downscales + re-encodes server-side before sending, so each
    # card is 20-40 KB instead of hundreds.
    max_width: int | None = Query(None, alias="maxWidth", ge=1, le=4000),
    max_height: int | None = Query(None, alias="maxHeight", ge=1, le=4000),
    quality: int | None = Query(None, ge=1, le=100),
    media_server=Depends(get_media_server),
    logger=Depends(get_logger),
    party_session: PartySession = Depends(require_host_token),
):
    access_token = party_session.party.host_access_token
    user_id = party_session.party.host_user_id
    try:
        emby_resp = await media_server.fetch_asset(
            AssetRequest(
                item_id=item_id,
                kind=type.lower(),
                credentials=ProviderCredentials(access_token or "", user_id or ""),
                index=index,
                max_width=max_width,
                max_height=max_height,
                quality=quality,
            )
        )
        if emby_resp.status_code == 200:
            ct = emby_resp.headers.get("Content-Type", "image/jpeg")
            if not ct.startswith("image/"):
                ct = "image/jpeg"
            return Response(
                content=emby_resp.content,
                media_type=ct,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        return Response(status_code=404)
    except Exception as e:
        logger.error("Error fetching image: error=%s", e.__class__.__name__)
        return Response(status_code=404)


@router.get(
    "/subtitles/{item_id}/{media_source_id}/{subtitle_index}",
    responses={
        200: {
            "content": {"text/vtt": {}},
            "description": "WebVTT subtitle stream",
        },
        404: {"description": "Subtitle stream unavailable"},
        **PARTY_HOST_TOKEN_RESPONSES,
    },
)
async def api_subtitles(
    item_id: str,
    media_source_id: str,
    subtitle_index: int,
    media_server=Depends(get_media_server),
    logger=Depends(get_logger),
    party_session: PartySession = Depends(require_host_token),
):
    access_token = party_session.party.host_access_token
    user_id = party_session.party.host_user_id
    try:
        emby_resp = await media_server.fetch_asset(
            AssetRequest(
                item_id=item_id,
                kind="subtitle",
                credentials=ProviderCredentials(access_token or "", user_id or ""),
                index=subtitle_index,
                media_source_id=media_source_id,
            )
        )
        if emby_resp.status_code == 200:
            return Response(
                content=emby_resp.content,
                media_type="text/vtt",
                headers={
                    "X-Content-Type-Options": "nosniff",
                },
            )
        return Response(status_code=404)
    except Exception as e:
        logger.error("Error fetching subtitle: error=%s", type(e).__name__)
        return Response(status_code=404)
