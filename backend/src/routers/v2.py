"""Provider-neutral REST v2 routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from backend.src.dependencies import (
    PARTY_HOST_RESPONSES,
    PARTY_HOST_TOKEN_RESPONSES,
    PARTY_UNLOCKED_RESPONSES,
    PartySession,
    get_config,
    get_logger,
    get_media_server,
    get_party_manager,
    get_sio,
    require_host_token,
    require_party_host,
    require_party_unlocked,
)
from backend.src.providers.models import (
    AssetRequest,
    CatalogFilters,
    CatalogPage,
    CatalogQuery,
    CatalogScope,
    CatalogSort,
    ProviderCredentials,
)
from backend.src.routers.auth import api_auth_status, api_login, api_logout
from backend.src.v2_schemas import (
    ActionResultV2,
    AuthStatusV2,
    CatalogQueryV2,
    FavoriteMutationV2,
    FavoriteResultV2,
    IntroSegmentV2,
    LoginRequest,
    LoginResponseV2,
    LogoutResponseV2,
    MediaItemDetailsV2,
    MediaPageV2,
    MediaServerInfoV2,
    PlayedMutationV2,
    PlayedResultV2,
    PlaylistCreatedV2,
    PlaylistCreateV2,
    PlaylistItemAddV2,
    PrefixesV2,
    StreamCatalogV2,
)

router = APIRouter(prefix="/api/v2", tags=["v2"])


def _catalog_query(body: CatalogQueryV2) -> CatalogQuery:
    return CatalogQuery(
        scope=CatalogScope(
            parent_id=body.scope.parent_id,
            include_kinds=tuple(body.scope.include_kinds),
            media_kinds=tuple(body.scope.media_kinds),
            recursive=body.scope.recursive,
        ),
        page=CatalogPage(start=body.page.start, limit=body.page.limit),
        sort=CatalogSort(field=body.sort.field, direction=body.sort.direction),
        filters=CatalogFilters(**body.filters.model_dump(mode="python")),
        search_term=body.search_term,
        anchor_prefix=body.anchor_prefix,
    )


@router.get("/media-server", response_model=MediaServerInfoV2)
def media_server_info(provider=Depends(get_media_server)):
    return MediaServerInfoV2(
        media_server_type=provider.identity.type,
        display_name=provider.identity.display_name,
    )


@router.post("/auth/login", response_model=LoginResponseV2)
async def login(
    body: LoginRequest,
    request: Request,
    config=Depends(get_config),
    provider=Depends(get_media_server),
    party_manager=Depends(get_party_manager),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
):
    result = await api_login(body, request, config, provider, party_manager, sio, logger)
    return LoginResponseV2(
        **result.model_dump(),
        media_server_type=provider.identity.type,
    )


@router.post("/auth/logout", response_model=LogoutResponseV2)
async def logout(
    request: Request,
    party_manager=Depends(get_party_manager),
    sio=Depends(get_sio),
    logger=Depends(get_logger),
):
    result = await api_logout(request, party_manager, sio, logger)
    return LogoutResponseV2(success=result.success, message=result.message)


@router.get("/auth/status", response_model=AuthStatusV2)
def auth_status(
    request: Request,
    config=Depends(get_config),
    provider=Depends(get_media_server),
    party_manager=Depends(get_party_manager),
):
    result = api_auth_status(request, config, party_manager)
    return AuthStatusV2(
        **result.model_dump(),
        media_server_type=provider.identity.type,
    )


@router.get(
    "/libraries",
    response_model=MediaPageV2,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Media server unavailable"}},
)
async def libraries(
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    page = await provider.browse_libraries(credentials)
    return MediaPageV2.model_validate(asdict(page))


@router.post(
    "/items/query",
    response_model=MediaPageV2,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Media server unavailable"}},
)
async def query_items(
    body: CatalogQueryV2,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    page = await provider.query_catalog(_catalog_query(body), credentials)
    return MediaPageV2.model_validate(asdict(page))


@router.post(
    "/items/prefixes",
    response_model=PrefixesV2,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Media server unavailable"}},
)
async def item_prefixes(
    body: CatalogQueryV2,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    prefixes = await provider.query_prefixes(_catalog_query(body), credentials)
    return PrefixesV2(prefixes=list(prefixes))


@router.get(
    "/items/search",
    response_model=MediaPageV2,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Media server unavailable"}},
)
async def search_items(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    page = await provider.search_catalog(q.strip(), limit, credentials)
    return MediaPageV2.model_validate(asdict(page))


@router.get(
    "/items/{item_id}",
    response_model=MediaItemDetailsV2,
    responses={
        **PARTY_UNLOCKED_RESPONSES,
        404: {"description": "Item not found"},
        502: {"description": "Media server unavailable"},
    },
)
async def item_details(
    item_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    item = await provider.get_details(item_id, credentials)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return MediaItemDetailsV2.model_validate(asdict(item))


@router.get(
    "/items/{item_id}/images/{image_type}",
    responses={
        200: {"content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}}},
        404: {"description": "Image unavailable"},
        **PARTY_HOST_TOKEN_RESPONSES,
    },
)
async def item_image(
    item_id: str,
    image_type: Literal["primary", "backdrop", "logo", "thumb", "art", "banner"],
    index: int | None = Query(None, ge=0, le=99),
    max_width: int | None = Query(None, ge=1, le=4000),
    max_height: int | None = Query(None, ge=1, le=4000),
    quality: int | None = Query(None, ge=1, le=100),
    party_session: PartySession = Depends(require_host_token),
    provider=Depends(get_media_server),
):
    party = party_session.party
    upstream = await provider.fetch_asset(
        AssetRequest(
            item_id=item_id,
            kind=image_type,
            credentials=ProviderCredentials(
                access_token=party.host_access_token or "",
                user_id=party.host_user_id or "",
            ),
            index=index,
            max_width=max_width,
            max_height=max_height,
            quality=quality,
        )
    )
    if upstream.status_code != 200:
        return Response(status_code=404)
    content_type = upstream.headers.get("Content-Type", "image/jpeg")
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get(
    "/items/{item_id}/subtitles/{media_source_id}/{subtitle_index}",
    responses={
        200: {"content": {"text/vtt": {}}},
        404: {"description": "Subtitle unavailable"},
        **PARTY_HOST_TOKEN_RESPONSES,
    },
)
async def item_subtitle(
    item_id: str,
    media_source_id: str,
    subtitle_index: int,
    party_session: PartySession = Depends(require_host_token),
    provider=Depends(get_media_server),
):
    party = party_session.party
    upstream = await provider.fetch_asset(
        AssetRequest(
            item_id=item_id,
            kind="subtitle",
            credentials=ProviderCredentials(
                access_token=party.host_access_token or "",
                user_id=party.host_user_id or "",
            ),
            index=subtitle_index,
            media_source_id=media_source_id,
        )
    )
    if upstream.status_code != 200:
        return Response(status_code=404)
    return Response(
        content=upstream.content,
        media_type="text/vtt",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get(
    "/items/{item_id}/intro",
    response_model=IntroSegmentV2,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def item_intro(
    item_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    segment = await provider.get_intro(
        item_id,
        ProviderCredentials(
            access_token=party.host_access_token or "",
            user_id=party.host_user_id or "",
        ),
    )
    if segment is None:
        return IntroSegmentV2(has_intro=False)
    return IntroSegmentV2(
        has_intro=True,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        duration_seconds=segment.end_seconds - segment.start_seconds,
    )


@router.get(
    "/items/{item_id}/streams",
    response_model=StreamCatalogV2,
    responses=PARTY_UNLOCKED_RESPONSES,
)
async def item_streams(
    item_id: str,
    media_source_id: str | None = None,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    streams = await provider.get_streams(
        item_id,
        media_source_id,
        ProviderCredentials(
            access_token=party.host_access_token or "",
            user_id=party.host_user_id or "",
        ),
    )
    return StreamCatalogV2.model_validate(asdict(streams))


@router.get(
    "/items/{series_id}/seasons",
    response_model=MediaPageV2,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Media server unavailable"}},
)
async def series_seasons(
    series_id: str,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    page = await provider.get_seasons(series_id, credentials)
    return MediaPageV2.model_validate(asdict(page))


@router.get(
    "/items/{series_id}/episodes",
    response_model=MediaPageV2,
    responses={**PARTY_UNLOCKED_RESPONSES, 502: {"description": "Media server unavailable"}},
)
async def series_episodes(
    series_id: str,
    season_id: str | None = None,
    party_session: PartySession = Depends(require_party_unlocked),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    page = await provider.get_episodes(series_id, season_id, credentials)
    return MediaPageV2.model_validate(asdict(page))


@router.put(
    "/items/{item_id}/favorite",
    response_model=FavoriteResultV2,
    responses=PARTY_HOST_RESPONSES,
)
async def set_favorite(
    item_id: str,
    body: FavoriteMutationV2,
    party_session: PartySession = Depends(require_party_host),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    await provider.set_favorite(item_id, body.favorite, credentials)
    return FavoriteResultV2(success=True, favorite=body.favorite)


@router.put(
    "/items/{item_id}/played",
    response_model=PlayedResultV2,
    responses=PARTY_HOST_RESPONSES,
)
async def set_played(
    item_id: str,
    body: PlayedMutationV2,
    party_session: PartySession = Depends(require_party_host),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    await provider.set_played(item_id, body.played, credentials)
    return PlayedResultV2(success=True, played=body.played)


@router.get(
    "/playlists",
    response_model=MediaPageV2,
    responses=PARTY_HOST_RESPONSES,
)
async def playlists(
    party_session: PartySession = Depends(require_party_host),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    page = await provider.list_playlists(credentials)
    return MediaPageV2.model_validate(asdict(page))


@router.post(
    "/playlists",
    response_model=PlaylistCreatedV2,
    responses=PARTY_HOST_RESPONSES,
    status_code=201,
)
async def create_playlist(
    body: PlaylistCreateV2,
    party_session: PartySession = Depends(require_party_host),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    playlist_id = await provider.create_playlist(body.name, credentials)
    return PlaylistCreatedV2(id=playlist_id, name=body.name)


@router.post(
    "/playlists/{playlist_id}/items",
    response_model=ActionResultV2,
    responses=PARTY_HOST_RESPONSES,
)
async def add_playlist_item(
    playlist_id: str,
    body: PlaylistItemAddV2,
    party_session: PartySession = Depends(require_party_host),
    provider=Depends(get_media_server),
):
    party = party_session.party
    credentials = ProviderCredentials(
        access_token=party.host_access_token or "",
        user_id=party.host_user_id or "",
    )
    await provider.add_playlist_item(playlist_id, body.item_id, credentials)
    return ActionResultV2(success=True)
