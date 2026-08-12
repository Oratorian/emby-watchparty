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
    get_config,
    get_emby_client,
    get_emby_gateway,
    get_logger,
    require_host_token,
    require_party_unlocked,
)
from backend.src.schemas import IntroResponse

# Every route here reaches Emby, so 502 is declared once on the router rather
# than repeated per route. See the same note in routers/library.py.
router = APIRouter(
    prefix="/api",
    tags=["media"],
    responses={502: {"description": "Emby upstream unavailable"}},
)


@router.get(
    "/intro/{item_id}",
    response_model=IntroResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def get_intro_info(
    item_id: str,
    config=Depends(get_config),
    _emby_client=Depends(get_emby_client),
    emby_gateway=Depends(get_emby_gateway),
    logger=Depends(get_logger),
    _party_session: PartySession = Depends(require_party_unlocked),
):
    logger.debug(f"Fetching intro info for item ID: {item_id}")
    # /emby/Items/Intros is an admin-only endpoint and requires the
    # server API key from .env, NOT the host's user access_token. A
    # user-scoped token (even from an Emby admin) gets a 403 here.
    # Carried over from the 1.x fix for issue #29.
    try:
        resp = await emby_gateway.get(
            "/emby/Items/Intros",
            params={"api_key": config.EMBY_API_KEY},
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        if resp.status_code == 200:
            for intro in resp.json():
                if str(intro.get("Id")) == str(item_id):
                    start = intro.get("Start", 0) / 10_000_000
                    end = intro.get("End", 0) / 10_000_000
                    logger.info(f"Found intro for {item_id}: {start:.2f}s - {end:.2f}s")
                    return IntroResponse(hasIntro=True, start=start, end=end, duration=end - start)
        return IntroResponse(hasIntro=False)
    except Exception as e:
        logger.warning("Intro fetch failed item=%s error=%s", item_id, type(e).__name__)
        return IntroResponse(hasIntro=False)


@router.get(
    "/image/{item_id}",
    responses={
        200: {
            "content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}},
            "description": "Item poster / image bytes proxied from Emby",
        },
        404: {"description": "No such image"},
        **PARTY_HOST_TOKEN_RESPONSES,
    },
)
async def api_image(
    item_id: str,
    type: Literal["Primary", "Backdrop", "Logo", "Thumb", "Art", "Banner"] = Query("Primary"),
    index: int | None = Query(None, ge=0, le=99),
    # Optional sizing forwarded to Emby. Library card thumbnails only
    # need ~240x360, but the original 2.0 endpoint proxied the full
    # poster bytes (often ~1000px wide / hundreds of KB) which made
    # the library card grid feel sluggish on throttled connections
    # (reported in beta12 by xyxxyxxy). With these params Emby
    # downscales + re-encodes server-side before sending, so each
    # card is 20-40 KB instead of hundreds.
    max_width: int | None = Query(None, alias="maxWidth", ge=1, le=4000),
    max_height: int | None = Query(None, alias="maxHeight", ge=1, le=4000),
    quality: int | None = Query(None, ge=1, le=100),
    emby_client=Depends(get_emby_client),
    emby_gateway=Depends(get_emby_gateway),
    logger=Depends(get_logger),
    party_session: PartySession = Depends(require_host_token),
):
    access_token = party_session.party.host_access_token
    user_id = party_session.party.host_user_id
    image_url = emby_client.get_image_url(
        item_id,
        type,
        access_token=access_token,
        max_width=max_width,
        max_height=max_height,
        quality=quality,
        image_index=index,
    )
    try:
        emby_resp = await emby_gateway.get(
            image_url, headers=emby_client._headers(access_token, user_id)
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
    config=Depends(get_config),
    emby_client=Depends(get_emby_client),
    emby_gateway=Depends(get_emby_gateway),
    logger=Depends(get_logger),
    party_session: PartySession = Depends(require_host_token),
):
    access_token = party_session.party.host_access_token
    user_id = party_session.party.host_user_id
    try:
        subtitle_url = (
            f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{media_source_id}"
            f"/Subtitles/{subtitle_index}/Stream.vtt?api_key={access_token}"
        )
        emby_resp = await emby_gateway.get(
            subtitle_url, headers=emby_client._headers(access_token, user_id)
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
