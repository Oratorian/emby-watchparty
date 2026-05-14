"""
Library Router - Emby library browsing and search.

Every route is gated by `require_party_unlocked`: the caller must hold
a party-bound session cookie AND the party must have a current host
whose Emby access_token signs the upstream call. See docs/AUTH-DESIGN.md.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from backend.src.dependencies import (
    PartySession,
    get_emby_client,
    get_logger,
    require_party_unlocked,
)
from backend.src.schemas import (
    LibraryItemsResponse,
    ItemDetailsResponse,
    StreamsResponse,
)

router = APIRouter(prefix="/api", tags=["library"])


def _host_creds(party_session: PartySession) -> tuple[str, str]:
    """Pull (access_token, user_id) for the party's current host."""
    party = party_session.party
    return party["host_access_token"], party["host_user_id"]


@router.get("/libraries", response_model=LibraryItemsResponse)
def api_libraries(
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    return emby_client.get_libraries(access_token=access_token, user_id=user_id)


@router.get("/items", response_model=LibraryItemsResponse)
def api_items(
    parentId: Optional[str] = None,
    type: Optional[str] = None,
    recursive: bool = False,
    startIndex: Optional[int] = None,
    limit: Optional[int] = None,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    return emby_client.get_items(
        parent_id=parentId,
        item_type=type,
        recursive=recursive,
        start_index=startIndex,
        limit=limit,
        access_token=access_token,
        user_id=user_id,
    )


@router.get("/search", response_model=LibraryItemsResponse)
def api_search(
    q: str = Query(""),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    if not q.strip():
        return {"Items": []}
    access_token, user_id = _host_creds(party_session)
    return emby_client.search_items(q.strip(), access_token=access_token, user_id=user_id)


@router.get("/item/{item_id}", response_model=ItemDetailsResponse)
def api_item_details(
    item_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    details = emby_client.get_item_details(item_id, access_token=access_token, user_id=user_id)
    if details:
        return details
    # ItemDetailsResponse requires Id and Name, so the previous
    # {"error": "..."} return tripped FastAPI response validation
    # and surfaced as a 500. 404 is the honest answer.
    raise HTTPException(status_code=404, detail="Item not found")


@router.get("/item/{item_id}/streams", response_model=StreamsResponse)
def api_item_streams(
    item_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
    logger=Depends(get_logger),
):
    logger.info(f"Fetching streams for item ID: {item_id}")
    access_token, user_id = _host_creds(party_session)

    playback_info = emby_client.get_playback_info(
        item_id, access_token=access_token, user_id=user_id
    )
    if not playback_info:
        playback_info = emby_client.get_item_details(
            item_id, access_token=access_token, user_id=user_id
        )

    if not playback_info:
        # Stream metadata is gone; tell the caller honestly rather than
        # returning an empty StreamsResponse with a silently-dropped
        # error field.
        raise HTTPException(
            status_code=502,
            detail="Could not fetch stream information from Emby",
        )

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
