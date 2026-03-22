"""
Library Router - Emby library browsing and search
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from backend.src.dependencies import get_emby_client, get_logger

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/libraries")
def api_libraries(emby_client=Depends(get_emby_client)):
    return emby_client.get_libraries()


@router.get("/items")
def api_items(
    parentId: Optional[str] = None,
    type: Optional[str] = None,
    recursive: bool = False,
    startIndex: Optional[int] = None,
    limit: Optional[int] = None,
    emby_client=Depends(get_emby_client),
):
    return emby_client.get_items(parentId, type, recursive, startIndex, limit)


@router.get("/search")
def api_search(q: str = Query(""), emby_client=Depends(get_emby_client)):
    if not q.strip():
        return {"Items": []}
    return emby_client.search_items(q.strip())


@router.get("/item/{item_id}")
def api_item_details(item_id: str, emby_client=Depends(get_emby_client)):
    details = emby_client.get_item_details(item_id)
    if details:
        return details
    return {"error": "Item not found"}


@router.get("/item/{item_id}/streams")
def api_item_streams(item_id: str, emby_client=Depends(get_emby_client), logger=Depends(get_logger)):
    logger.info(f"Fetching streams for item ID: {item_id}")

    playback_info = emby_client.get_playback_info(item_id)
    if not playback_info:
        playback_info = emby_client.get_item_details(item_id)

    if not playback_info:
        return {"audio": [], "subtitles": [], "error": "Could not fetch stream information"}

    audio_streams = []
    subtitle_streams = []
    media_source_id = None
    media_streams = []

    if "MediaSources" in playback_info and playback_info["MediaSources"]:
        media_streams = playback_info["MediaSources"][0].get("MediaStreams", [])
        media_source_id = playback_info["MediaSources"][0].get("Id")
    elif "MediaStreams" in playback_info:
        media_streams = playback_info["MediaStreams"]

    for stream in media_streams:
        stream_type = stream.get("Type")
        if stream_type == "Audio":
            lang = stream.get("Language", "und")
            display_lang = stream.get("DisplayLanguage") or stream.get("DisplayTitle") or lang
            if lang == "und":
                display_lang = "Unknown"
            audio_streams.append({
                "index": stream.get("Index"),
                "language": lang,
                "displayLanguage": display_lang,
                "codec": stream.get("Codec", ""),
                "channels": stream.get("Channels", 0),
                "isDefault": stream.get("IsDefault", False),
                "title": stream.get("Title", ""),
            })
        elif stream_type == "Subtitle":
            codec = stream.get("Codec", "").lower()
            is_image = codec in ["pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub"]
            lang = stream.get("Language", "und")
            display_lang = stream.get("DisplayLanguage") or stream.get("DisplayTitle") or lang
            if lang == "und":
                display_lang = "Unknown"
            subtitle_streams.append({
                "index": stream.get("Index"),
                "language": lang,
                "displayLanguage": display_lang,
                "codec": stream.get("Codec", ""),
                "isDefault": stream.get("IsDefault", False),
                "isForced": stream.get("IsForced", False),
                "isExternal": stream.get("IsExternal", False),
                "isTextSubtitleStream": stream.get("IsTextSubtitleStream", False),
                "isPGS": is_image,
                "title": stream.get("Title", ""),
            })

    return {"audio": audio_streams, "subtitles": subtitle_streams, "media_source_id": media_source_id}
