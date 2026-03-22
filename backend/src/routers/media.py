"""
Media Router - Intro info, image proxy, subtitle proxy
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
import requests as http_requests

from backend.src.dependencies import get_config, get_emby_client, get_logger
from backend.src.schemas import IntroResponse

router = APIRouter(prefix="/api", tags=["media"])


@router.get("/intro/{item_id}", response_model=IntroResponse)
def get_intro_info(item_id: str, config=Depends(get_config),
                   emby_client=Depends(get_emby_client), logger=Depends(get_logger)):
    logger.debug(f"Fetching intro info for item ID: {item_id}")
    try:
        resp = http_requests.get(
            f"{config.EMBY_SERVER_URL}/emby/Items/Intros",
            params={"api_key": emby_client.api_key},
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
        logger.debug(f"Intro fetch failed for {item_id}: {e}")
        return IntroResponse(hasIntro=False)


@router.get("/image/{item_id}")
def api_image(item_id: str, type: str = Query("Primary"),
              emby_client=Depends(get_emby_client), logger=Depends(get_logger)):
    image_url = emby_client.get_image_url(item_id, type)
    try:
        emby_resp = http_requests.get(image_url, headers=emby_client.headers)
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
        logger.error(f"Error fetching image: {e}")
        return Response(status_code=404)


@router.get("/subtitles/{item_id}/{media_source_id}/{subtitle_index}")
def api_subtitles(item_id: str, media_source_id: str, subtitle_index: int,
                  config=Depends(get_config), emby_client=Depends(get_emby_client),
                  logger=Depends(get_logger)):
    try:
        subtitle_url = (
            f"{config.EMBY_SERVER_URL}/emby/Videos/{item_id}/{media_source_id}"
            f"/Subtitles/{subtitle_index}/Stream.vtt?api_key={emby_client.api_key}"
        )
        emby_resp = http_requests.get(subtitle_url, headers=emby_client.headers)
        if emby_resp.status_code == 200:
            return Response(
                content=emby_resp.content,
                media_type="text/vtt",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        return Response(status_code=404)
    except Exception as e:
        logger.error(f"Error fetching subtitle: {e}")
        return Response(status_code=404)
