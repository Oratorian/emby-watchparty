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
    PartyListItem,
    PartyListResponse,
    StaticSessionResponse,
)

router = APIRouter(prefix="/api/party", tags=["party"])


@router.get("/static-session", response_model=StaticSessionResponse)
def static_session(config=Depends(get_config)):
    """Return static session ID if enabled, or null."""
    if config.STATIC_SESSION_ENABLED:
        return {"party_id": config.STATIC_SESSION_ID.upper()}
    return {"party_id": None}


@router.get("/list", response_model=PartyListResponse)
def list_parties(
    config=Depends(get_config),
    party_manager=Depends(get_party_manager),
    logger=Depends(get_logger),
):
    """Public listing of active parties for the index page.

    Only advertised when REQUIRE_LOGIN is off; otherwise the set of open
    parties and what they are watching is not exposed. Lists every party
    that has at least one member (the static-session party is excluded
    since the index auto-redirects into it). Clicking a listed party
    joins it, which triggers the late-joiner vote when a video is playing.

    Logging note: this route is polled every ~5s per open index tab, so it
    deliberately stays at DEBUG (no INFO spam). A malformed party is logged
    at WARNING and skipped rather than failing the whole listing.
    """
    if config.REQUIRE_LOGIN:
        logger.debug("Party list requested; REQUIRE_LOGIN on, not advertising parties")
        return PartyListResponse(require_login=True, parties=[])

    static_id = party_manager.static_party_id
    items: list[PartyListItem] = []
    for code, party in party_manager.get_all().items():
        if code == static_id:
            continue
        users = party.get("users", {})
        if not users:
            continue
        try:
            cv = party.get("current_video")
            items.append(PartyListItem(
                code=code,
                title=cv.get("title") if cv else None,
                user_count=len(users),
                playing=cv is not None,
                locked=not party.get("host_access_token"),
            ))
        except Exception as e:
            # One bad party record should not break the whole index listing.
            logger.warning(f"Skipping party {code} in public listing: {e}")

    logger.debug(f"Party list served: {len(items)} active part{'y' if len(items) == 1 else 'ies'}")
    return PartyListResponse(require_login=False, parties=items)


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

    # If the caller previously logged in via the standalone /api/admin/login
    # flow, their session carries an Emby access_token. Auto-promote them
    # to host of the new party instead of forcing a second login. This is
    # also the path that lets an admin do "configure stuff in /admin, come
    # back, create a party" without re-typing credentials.
    session = request.session
    stashed_token = session.get("admin_emby_token")
    stashed_user_id = session.get("admin_emby_user_id")
    stashed_username = session.get("admin_username")
    stashed_is_admin = session.get("admin_emby_is_admin", False)

    if stashed_token and stashed_user_id and body.client_id:
        party_id = party_manager.create_party()
        display_name = body.display_name or stashed_username or "Host"
        party_manager.set_host(
            party_id,
            client_id=body.client_id,
            user_id=stashed_user_id,
            access_token=stashed_token,
            username=stashed_username or "Host",
            is_admin=bool(stashed_is_admin),
        )
        request.session["party_id"] = party_id
        request.session["client_id"] = body.client_id
        request.session["display_name"] = display_name
        logger.info(
            f"Created party {party_id} with stashed admin '{stashed_username}' "
            f"auto-promoted to host (admin={stashed_is_admin})"
        )
        return CreatePartyResponse(
            party_id=party_id,
            url=f"{prefix}/party/{party_id}",
            is_host=True,
            host_username=stashed_username,
            is_admin=bool(stashed_is_admin),
        )

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


@router.post("/leave")
def leave_party(request: Request, logger=Depends(get_logger)):
    """Drop the party-bound session cookie.

    The Socket.IO `leave_party` event handles the in-memory party state
    (removing the user from `party["users"]` and so on), but it can't
    touch the HTTP session cookie. Without this endpoint a user who
    leaves and then visits `/admin` or `/version` would still have
    `party_id` in their session, and "Back to Party" would relaunch the
    old (or freshly-empty) party. Calling this on leave keeps the
    cookie in sync with the user's actual party membership.
    """
    session = request.session
    party_id = session.pop("party_id", None)
    session.pop("client_id", None)
    session.pop("display_name", None)
    session.pop("avatar_uuid", None)
    if party_id:
        logger.info(f"Session unbound from party {party_id}")
    return {"success": True}


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
