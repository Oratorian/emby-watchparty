"""
Library Router - Emby library browsing and search.

Every route is gated by `require_party_unlocked`: the caller must hold
a party-bound session cookie AND the party must have a current host
whose Emby access_token signs the upstream call.
"""

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.src.dependencies import (
    PARTY_UNLOCKED_RESPONSES,
    PartySession,
    get_emby_client,
    get_logger,
    require_party_host,
    require_party_unlocked,
)
from backend.src.schemas import (
    ActionSuccessResponse,
    FavoriteRequest,
    FavoriteResponse,
    FilterOptionsResponse,
    GroupedSearchResponse,
    ItemChildrenResponse,
    ItemDetailsResponse,
    ItemSectionResponse,
    LibraryItemsResponse,
    LibraryPrefixesResponse,
    LibraryQueryRequest,
    PlayedRequest,
    PlayedResponse,
    PlaylistAddRequest,
    PlaylistCreateRequest,
    PlaylistCreateResponse,
    PlaylistListResponse,
    StreamsResponse,
)

router = APIRouter(prefix="/api", tags=["library"])


def _host_creds(party_session: PartySession) -> tuple[str, str]:
    """Pull (access_token, user_id) for the party's current host."""
    party = party_session.party
    access_token = party.host_access_token
    user_id = party.host_user_id
    if access_token is None or user_id is None:
        raise HTTPException(status_code=423, detail="Party library is locked")
    return access_token, user_id


def _normalize_items_response(payload: dict) -> dict:
    """Keep permissive Emby rows from violating the strict viewer contract."""
    raw_items = payload.get("Items")
    if not isinstance(raw_items, list):
        return payload
    items = [
        item for item in raw_items if isinstance(item, dict) and str(item.get("Name") or "").strip()
    ]
    if len(items) == len(raw_items):
        return payload
    normalized = {**payload, "Items": items}
    total = payload.get("TotalRecordCount")
    if isinstance(total, int):
        normalized["TotalRecordCount"] = max(0, total - (len(raw_items) - len(items)))
    return normalized


@router.get(
    "/libraries",
    response_model=LibraryItemsResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def api_libraries(
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    return await emby_client.get_libraries(access_token=access_token, user_id=user_id)


@router.get(
    "/items/prefixes",
    response_model=LibraryPrefixesResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def api_item_prefixes(
    parent_id: str | None = Query(None, alias="parentId"),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    prefixes = await emby_client.get_item_prefixes(
        parent_id=parent_id,
        access_token=access_token,
        user_id=user_id,
    )
    return {
        "Prefixes": [row["Name"] for row in prefixes if isinstance(row, dict) and row.get("Name")]
    }


@router.get(
    "/items",
    response_model=LibraryItemsResponse,
    responses={
        **PARTY_UNLOCKED_RESPONSES,
        502: {"description": "Emby upstream unavailable"},
    },
)
async def api_items(
    response: Response,
    parent_id: str | None = Query(None, alias="parentId"),
    type: str | None = None,
    recursive: bool = False,
    start_index: int | None = Query(None, alias="startIndex"),
    limit: int | None = None,
    sort_mode: str = Query("default", alias="sortMode", pattern="^(default|alphabetical)$"),
    anchor_prefix: str | None = Query(None, alias="anchorPrefix", min_length=1, max_length=8),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    response.headers["Cache-Control"] = "no-store"
    try:
        payload = await emby_client.get_items(
            parent_id=parent_id,
            item_type=type,
            recursive=recursive,
            start_index=start_index,
            limit=limit,
            sort_mode=sort_mode,
            anchor_prefix=anchor_prefix,
            access_token=access_token,
            user_id=user_id,
        )
        # Same upstream endpoint as POST /items/query, so it meets the same
        # nameless rows. The guard was wired into the query twin only, which
        # left the default browse to 500 on the exact row it was written for.
        return _normalize_items_response(payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Emby upstream unavailable",
        ) from exc


@router.post(
    "/items/query",
    response_model=LibraryItemsResponse,
    responses={
        **PARTY_UNLOCKED_RESPONSES,
        502: {"description": "Emby upstream unavailable"},
    },
)
async def api_query_items(
    query: LibraryQueryRequest,
    response: Response,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    response.headers["Cache-Control"] = "no-store"
    try:
        payload = await emby_client.query_items(
            query.model_dump(), access_token=access_token, user_id=user_id
        )
        return _normalize_items_response(payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Emby upstream unavailable") from exc


@router.post(
    "/items/prefixes/query",
    response_model=LibraryPrefixesResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def api_query_prefixes(
    query: LibraryQueryRequest,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    rows = await emby_client.query_items(
        query.model_dump(),
        access_token=access_token,
        user_id=user_id,
        prefixes=True,
    )
    return {"Prefixes": [row["Name"] for row in rows if isinstance(row, dict) and row.get("Name")]}


def _filter_values(payload: dict | None, *, uppercase_labels: bool = False) -> list[dict[str, str]]:
    if not payload:
        return []
    return [
        {
            "value": str(item["Name"]),
            "label": (str(item["Name"]).upper() if uppercase_labels else str(item["Name"])),
        }
        for item in payload.get("Items", [])
        if item.get("Name")
    ]


_US_MOVIE_RATING_ORDER = (
    "G",
    "PG",
    "PG-13",
    "R",
    "NC-17",
    "NR",
    "NOT RATED",
)


def _prioritize_parental_ratings(
    values: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Put familiar US movie ratings first, preserving all other source order."""
    priority = {rating: index for index, rating in enumerate(_US_MOVIE_RATING_ORDER)}
    return sorted(
        values,
        key=lambda value: priority.get(value["value"].strip().upper(), len(priority)),
    )


@router.get(
    "/items/filter-options",
    response_model=FilterOptionsResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def api_filter_options(
    parent_id: str | None = Query(None, alias="parentId"),
    include_item_types: str | None = Query(None, alias="includeItemTypes"),
    media_types: str | None = Query(None, alias="mediaTypes"),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    catalogs = await emby_client.get_filter_options(
        parent_id=parent_id,
        include_item_types=include_item_types,
        media_types=media_types,
        access_token=access_token,
        user_id=user_id,
    )
    controls: list[dict] = [
        {
            "id": "playstate",
            "label": "Playstate",
            "kind": "select",
            "values": [
                {"value": "any", "label": "Any"},
                {"value": "unplayed", "label": "Unplayed"},
                {"value": "played", "label": "Played"},
                {"value": "resumable", "label": "In progress"},
            ],
        },
        {"id": "favorite", "label": "Favorite", "kind": "toggle", "values": []},
        {"id": "duplicates", "label": "Duplicates", "kind": "toggle", "values": []},
    ]
    labels = {
        "genre": "Genre",
        "studio": "Studio",
        "tag": "Tag",
        "year": "Year",
        "official_rating": "Parental rating",
        "container": "Container",
        "video_codec": "Video codec",
        "audio_codec": "Audio codec",
        "audio_layout": "Audio layout",
        "subtitle_codec": "Subtitle codec",
    }
    for control_id, label in labels.items():
        values = _filter_values(
            catalogs.get(control_id),
            uppercase_labels=control_id
            in {
                "container",
                "video_codec",
                "audio_codec",
                "audio_layout",
                "subtitle_codec",
            },
        )
        if control_id == "official_rating":
            values = _prioritize_parental_ratings(values)
        if values:
            controls.append({"id": control_id, "label": label, "kind": "multi", "values": values})
    controls.extend(
        [
            {
                "id": "video_type",
                "label": "Video type",
                "kind": "multi",
                "values": [
                    {"value": value, "label": value}
                    for value in ("VideoFile", "Bluray", "Dvd", "Iso")
                ],
            },
            {
                "id": "resolution",
                "label": "Resolution",
                "kind": "select",
                "values": [{"value": "any", "label": "Any"}]
                + [{"value": value, "label": value} for value in ("4K", "1080p", "720p", "SD")],
            },
            {"id": "is_3d", "label": "3D", "kind": "toggle", "values": []},
        ]
    )
    for control_id, label in (
        ("subtitles", "Subtitles"),
        ("trailers", "Trailers"),
        ("extras", "Extras"),
        ("theme_songs", "Theme songs"),
        ("theme_videos", "Theme videos"),
        ("locked", "Locked"),
        ("overview", "Overview"),
    ):
        positive_value, negative_value = (
            ("yes", "no") if control_id == "locked" else ("with", "without")
        )
        controls.append(
            {
                "id": control_id,
                "label": label,
                "kind": "select",
                "values": [
                    {"value": "any", "label": "Any"},
                    {"value": positive_value, "label": "With"},
                    {"value": negative_value, "label": "Without"},
                ],
            }
        )
    controls.append(
        {
            "id": "missing_provider_ids",
            "label": "Missing metadata",
            "kind": "multi",
            "values": [
                {"value": "imdb", "label": "IMDb Id"},
                {"value": "tmdb", "label": "MovieDb Id"},
                {"value": "tvdb", "label": "Tvdb Id"},
            ],
        }
    )
    return {"controls": controls}


@router.get(
    "/search",
    response_model=LibraryItemsResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def api_search(
    # Capped like its /search/grouped sibling. search_items ranks candidates
    # with a pure-Python edit distance, so cost grows with len(q) x len(title)
    # on a single event loop; an uncapped q stalls socket sync and HLS proxying
    # for every viewer in every party, not just the caller.
    q: str = Query("", min_length=0, max_length=200),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    if not q.strip():
        return {"Items": []}
    access_token, user_id = _host_creds(party_session)
    return await emby_client.search_items(q.strip(), access_token=access_token, user_id=user_id)


@router.get(
    "/search/grouped",
    response_model=GroupedSearchResponse,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def api_grouped_search(
    q: str = Query("", min_length=0, max_length=200),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    query = q.strip()
    if len(query) < 2:
        return {"query": query, "groups": []}
    access_token, user_id = _host_creds(party_session)
    result = await emby_client.search_items(
        query,
        access_token=access_token,
        user_id=user_id,
        include_item_types="Movie,Series,Episode,Person,BoxSet",
    )
    definitions = (
        ("movies", "Movies", {"Movie"}),
        ("series", "Series", {"Series"}),
        ("episodes", "Episodes", {"Episode"}),
        ("people", "People", {"Person"}),
        ("collections", "Collections", {"BoxSet"}),
    )
    items = result.get("Items", [])
    return {
        "query": query,
        "groups": [
            {
                "id": group_id,
                "label": label,
                "items": [item for item in items if item.get("Type") in types],
            }
            for group_id, label, types in definitions
            if any(item.get("Type") in types for item in items)
        ],
    }


@router.get(
    "/item/{item_id}",
    response_model=ItemDetailsResponse,
    responses={
        **PARTY_UNLOCKED_RESPONSES,
        404: {"description": "Item not found in Emby"},
    },
)
async def api_item_details(
    item_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    details = await emby_client.get_item_details(
        item_id, access_token=access_token, user_id=user_id
    )
    if details:
        return details
    # ItemDetailsResponse requires Id and Name, so the previous
    # {"error": "..."} return tripped FastAPI response validation
    # and surfaced as a 500. 404 is the honest answer.
    raise HTTPException(status_code=404, detail="Item not found")


@router.get(
    "/item/{item_id}/sections/{section}",
    response_model=ItemSectionResponse,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Optional section unavailable"}},
)
async def api_item_section(
    item_id: str,
    section: Literal["related", "trailers", "extras"],
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    try:
        items = await emby_client.get_item_section(
            item_id,
            section,
            access_token=access_token,
            user_id=user_id,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{section.title()} unavailable") from exc
    return {"section": section, "items": items}


@router.get("/item/{series_id}/seasons", response_model=ItemChildrenResponse)
async def api_series_seasons(
    series_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    items = await emby_client.get_series_seasons(
        series_id, access_token=access_token, user_id=user_id
    )
    return {"items": items}


@router.get("/item/{series_id}/episodes", response_model=ItemChildrenResponse)
async def api_series_episodes(
    series_id: str,
    season_id: str | None = Query(None, alias="seasonId"),
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    items = await emby_client.get_series_episodes(
        series_id,
        season_id,
        access_token=access_token,
        user_id=user_id,
    )
    return {"items": items}


@router.put("/item/{item_id}/favorite", response_model=FavoriteResponse)
async def api_set_favorite(
    item_id: str,
    body: FavoriteRequest,
    party_session: PartySession = Depends(require_party_host),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    await emby_client.set_favorite(
        item_id, body.favorite, access_token=access_token, user_id=user_id
    )
    return {"success": True, "favorite": body.favorite}


@router.put("/item/{item_id}/played", response_model=PlayedResponse)
async def api_set_played(
    item_id: str,
    body: PlayedRequest,
    party_session: PartySession = Depends(require_party_host),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    await emby_client.set_played(item_id, body.played, access_token=access_token, user_id=user_id)
    return {"success": True, "played": body.played}


@router.get("/playlists", response_model=PlaylistListResponse)
async def api_playlists(
    party_session: PartySession = Depends(require_party_host),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    items = await emby_client.get_playlists(access_token=access_token, user_id=user_id)
    return {"items": items}


@router.post("/playlists", response_model=PlaylistCreateResponse)
async def api_create_playlist(
    body: PlaylistCreateRequest,
    party_session: PartySession = Depends(require_party_host),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    playlist_id = await emby_client.create_playlist(
        body.name, access_token=access_token, user_id=user_id
    )
    return {"id": playlist_id, "name": body.name}


@router.post("/playlists/{playlist_id}/items", response_model=ActionSuccessResponse)
async def api_add_playlist_item(
    playlist_id: str,
    body: PlaylistAddRequest,
    party_session: PartySession = Depends(require_party_host),
    emby_client=Depends(get_emby_client),
):
    access_token, user_id = _host_creds(party_session)
    await emby_client.add_to_playlist(
        playlist_id,
        body.item_id,
        access_token=access_token,
        user_id=user_id,
    )
    return {"success": True}


@router.get(
    "/item/{item_id}/streams",
    response_model=StreamsResponse,
    responses={
        **PARTY_UNLOCKED_RESPONSES,
        502: {"description": "Could not fetch stream info from Emby"},
    },
)
async def api_item_streams(
    item_id: str,
    media_source_id: str | None = None,
    party_session: PartySession = Depends(require_party_unlocked),
    emby_client=Depends(get_emby_client),
    logger=Depends(get_logger),
):
    """List the audio + subtitle streams for an item, plus its
    alternate-version MediaSources.

    `media_source_id` is optional; when omitted, Emby returns every
    version and we pick the first one for the audio/subtitle lists
    (matches the historical default). When provided, Emby scopes the
    PlaybackInfo response to just that source so the audio/subtitle
    lists are version-specific -- the frontend re-fetches after a
    version switch so the dropdowns reflect the new file. The
    `versions` array is always the full list, so the Version dropdown
    knows every option regardless of which source is currently active.
    Addresses [#43](https://github.com/Oratorian/emby-watchparty/issues/43).
    """
    logger.info(
        f"Fetching streams for item ID: {item_id}"
        + (f" (media_source_id={media_source_id})" if media_source_id else "")
    )
    access_token, user_id = _host_creds(party_session)

    # When the caller asks for a specific version, ask Emby to scope
    # the response to that source. When they don't, ask for everything
    # so the versions list is complete (Emby returns every MediaSource
    # for an item when MediaSourceId is omitted).
    scoped_info = await emby_client.get_playback_info(
        item_id,
        media_source_id=media_source_id,
        access_token=access_token,
        user_id=user_id,
    )
    if not scoped_info:
        scoped_info = await emby_client.get_item_details(
            item_id, access_token=access_token, user_id=user_id
        )

    if not scoped_info:
        raise HTTPException(
            status_code=502,
            detail="Could not fetch stream information from Emby",
        )

    # The versions list always reflects the full set of MediaSources
    # for the item. When media_source_id was provided, scoped_info only
    # contains the requested version, so do a second unscoped call to
    # enumerate alternates -- otherwise the dropdown would collapse to
    # one entry the moment the user picks anything.
    if media_source_id:
        full_info = (
            await emby_client.get_playback_info(item_id, access_token=access_token, user_id=user_id)
            or scoped_info
        )
    else:
        full_info = scoped_info

    versions: list[dict] = []
    for source in full_info.get("MediaSources", []) or []:
        sid = source.get("Id")
        if not sid:
            continue
        versions.append(
            {
                "id": sid,
                "name": source.get("Name") or source.get("Container") or sid,
                "container": source.get("Container"),
                "run_time_ticks": source.get("RunTimeTicks"),
            }
        )

    audio_streams = []
    subtitle_streams = []
    resolved_media_source_id = None
    media_streams = []

    if scoped_info.get("MediaSources"):
        # When media_source_id was provided, Emby returns just that source.
        # When it was omitted, Emby returns every source and [0] is the
        # default version -- which is what every existing call site already
        # treats as "the" stream.
        primary = scoped_info["MediaSources"][0]
        media_streams = primary.get("MediaStreams", [])
        resolved_media_source_id = primary.get("Id")
    elif "MediaStreams" in scoped_info:
        media_streams = scoped_info["MediaStreams"]

    for stream in media_streams:
        stream_type = stream.get("Type")
        if stream_type == "Audio":
            lang = stream.get("Language", "und")
            display_lang = stream.get("DisplayLanguage") or stream.get("DisplayTitle") or lang
            if lang == "und":
                display_lang = "Unknown"
            audio_streams.append(
                {
                    "index": stream.get("Index"),
                    "language": lang,
                    "displayLanguage": display_lang,
                    "codec": stream.get("Codec", ""),
                    "channels": stream.get("Channels", 0),
                    "isDefault": stream.get("IsDefault", False),
                    "title": stream.get("Title", ""),
                }
            )
        elif stream_type == "Subtitle":
            codec = stream.get("Codec", "").lower()
            is_image = codec in ["pgssub", "pgs", "dvd_subtitle", "dvdsub", "vobsub"]
            lang = stream.get("Language", "und")
            display_lang = stream.get("DisplayLanguage") or stream.get("DisplayTitle") or lang
            if lang == "und":
                display_lang = "Unknown"
            subtitle_streams.append(
                {
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
                }
            )

    return {
        "audio": audio_streams,
        "subtitles": subtitle_streams,
        "media_source_id": resolved_media_source_id,
        "versions": versions,
    }
