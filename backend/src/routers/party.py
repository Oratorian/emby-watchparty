"""
Party Router -- create / join / probe.

`POST /api/party/create` branches on the runtime REQUIRE_LOGIN toggle:
anonymous create when off, Emby-authenticated create-as-host when on.
`POST /api/party/<id>/join` is always anonymous and issues the
party-bound session cookie used by every protected route.
See docs/AUTH-DESIGN.md.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.src.dependencies import (
    get_config, get_party_manager, get_logger, get_emby_client,
)
from backend.src.schemas import (
    CreatePartyRequest,
    CreatePartyResponse,
    JoinPartyRequest,
    JoinPartyResponse,
    PartyExistsResponse,
    PartyInfoResponse,
    StaticSessionResponse,
)

router = APIRouter(prefix="/api/party", tags=["party"])


@router.get("/static-session", response_model=StaticSessionResponse)
def static_session(config=Depends(get_config)):
    """Return static session ID if enabled, or null."""
    if config.STATIC_SESSION_ENABLED:
        return {"party_id": config.STATIC_SESSION_ID.upper()}
    return {"party_id": None}


@router.post("/create", response_model=CreatePartyResponse)
def create_party(
    request: Request,
    body: CreatePartyRequest | None = None,
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
    emby_client=Depends(get_emby_client),
    logger=Depends(get_logger),
):
    """Create a new watch party.

    When REQUIRE_LOGIN is off, anyone can create a party. The new party
    has no host -- the library stays locked until someone clicks
    "Login to Become Host" inside the party.

    When REQUIRE_LOGIN is on, the request must supply valid Emby
    credentials. The caller is authenticated, made host of the new
    party, and issued a party-bound session cookie atomically.
    """
    body = body or CreatePartyRequest()
    prefix = config.APP_PREFIX

    if config.REQUIRE_LOGIN:
        if not body.username or not body.password:
            return CreatePartyResponse(
                party_id="",
                url="",
                message="Emby login is required to create a party",
            )
        if not body.client_id:
            return CreatePartyResponse(
                party_id="",
                url="",
                message="client_id is required",
            )

        auth = emby_client.authenticate(body.username, body.password)
        if not auth:
            return CreatePartyResponse(
                party_id="",
                url="",
                message="Invalid Emby credentials",
            )

        party_id = party_manager.create_party()
        display_name = body.display_name or auth["username"]
        party_manager.set_host(
            party_id,
            client_id=body.client_id,
            user_id=auth["user_id"],
            access_token=auth["access_token"],
            username=auth["username"],
            is_admin=auth["is_admin"],
        )
        # Bind the creator's session to the new party in a single step.
        request.session["party_id"] = party_id
        request.session["client_id"] = body.client_id
        request.session["display_name"] = display_name
        logger.info(
            f"Created party {party_id} with host '{auth['username']}' "
            f"(admin={auth['is_admin']})"
        )
        return CreatePartyResponse(
            party_id=party_id,
            url=f"{prefix}/party/{party_id}",
            is_host=True,
            host_username=auth["username"],
            is_admin=auth["is_admin"],
        )

    # REQUIRE_LOGIN=false -- anonymous create.
    party_id = party_manager.create_party()
    logger.info(f"Created new watch party: {party_id} (anonymous)")
    return CreatePartyResponse(
        party_id=party_id,
        url=f"{prefix}/party/{party_id}",
    )


@router.post("/{party_id}/join", response_model=JoinPartyResponse)
def join_party(
    party_id: str,
    body: JoinPartyRequest,
    request: Request,
    party_manager=Depends(get_party_manager),
    logger=Depends(get_logger),
):
    """Issue the party-bound session cookie used by every protected route.

    Anonymous: no Emby credentials. The cookie carries `party_id`,
    `client_id`, and `display_name` so the Socket.IO connect handler
    and HTTP gates can attribute requests to this caller.
    """
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        return JoinPartyResponse(success=False, message="Party not found")
    if not body.client_id or not body.display_name:
        return JoinPartyResponse(
            success=False, message="client_id and display_name are required"
        )

    request.session["party_id"] = party_id
    request.session["client_id"] = body.client_id
    request.session["display_name"] = body.display_name
    if body.avatar_uuid:
        request.session["avatar_uuid"] = body.avatar_uuid
    else:
        request.session.pop("avatar_uuid", None)
    logger.info(
        f"Party {party_id} session bound for '{body.display_name}' "
        f"(client_id={body.client_id[:8]}...)"
    )

    return JoinPartyResponse(
        success=True,
        party_id=party_id,
        is_host=(party.get("host_client_id") == body.client_id),
        party_unlocked=party_manager.is_unlocked(party_id),
    )


@router.get("/{party_id}/exists", response_model=PartyExistsResponse)
def party_exists(party_id: str, party_manager=Depends(get_party_manager)):
    """Anonymous probe: does this party exist?

    Used by the join screen to validate a code before issuing the cookie.
    Returns only a boolean so it leaks no party state.
    """
    return PartyExistsResponse(exists=party_manager.exists(party_id.upper()))


@router.get("/{party_id}/info", response_model=PartyInfoResponse)
def party_info(party_id: str, party_manager=Depends(get_party_manager)):
    party = party_manager.get(party_id.upper())
    if not party:
        # 404 keeps the response_model satisfied; returning a dict
        # with {"error": "..."} would fail validation since
        # PartyInfoResponse requires id, users, and playback_state.
        raise HTTPException(status_code=404, detail="Party not found")
    return PartyInfoResponse(
        id=party["id"],
        users=list(party["users"].values()),
        current_video=party["current_video"],
        playback_state=party["playback_state"],
    )
