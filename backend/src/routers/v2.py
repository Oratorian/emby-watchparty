"""Provider-neutral REST v2 routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.src.dependencies import (
    PARTY_UNLOCKED_RESPONSES,
    PartySession,
    get_config,
    get_logger,
    get_media_server,
    get_party_manager,
    get_sio,
    require_party_unlocked,
)
from backend.src.providers.models import (
    CatalogPage,
    CatalogQuery,
    CatalogScope,
    CatalogSort,
    ProviderCredentials,
)
from backend.src.routers.auth import api_login
from backend.src.v2_schemas import (
    CatalogQueryV2,
    LoginRequest,
    LoginResponseV2,
    MediaItemDetailsV2,
    MediaPageV2,
    MediaServerInfoV2,
)

router = APIRouter(prefix="/api/v2", tags=["v2"])


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
    query = CatalogQuery(
        scope=CatalogScope(
            parent_id=body.scope.parent_id,
            include_kinds=tuple(body.scope.include_kinds),
            media_kinds=tuple(body.scope.media_kinds),
            recursive=body.scope.recursive,
        ),
        page=CatalogPage(start=body.page.start, limit=body.page.limit),
        sort=CatalogSort(field=body.sort.field, direction=body.sort.direction),
        search_term=body.search_term,
    )
    page = await provider.query_catalog(query, credentials)
    return MediaPageV2.model_validate(asdict(page))


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
