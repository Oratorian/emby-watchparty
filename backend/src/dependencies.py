"""
FastAPI dependency injection
Replaces the old Flask deps dict pattern.

Plus the party-bound session gates used to protect every route that
touches Emby on behalf of a watch party.
"""

import secrets
from collections.abc import MutableMapping
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, Request

from backend.src.admin_session_store import AdminSessionStore
from backend.src.avatar_store import AvatarStore
from backend.src.config import Config
from backend.src.domain import Party
from backend.src.emby_client import EmbyClient
from backend.src.emby_gateway import EmbyGateway
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.party_manager import PartyManager
from backend.src.stream_builder import StreamBuilder

LEGACY_ADMIN_SESSION_KEYS = (
    "admin_emby_token",
    "admin_emby_user_id",
    "admin_emby_is_admin",
    "admin_authenticated",
    "admin_username",
    "admin_session",
)


def scrub_legacy_admin_session(session: MutableMapping[str, object]) -> None:
    """Remove credentials written into signed cookies by pre-3.0 releases."""
    for key in LEGACY_ADMIN_SESSION_KEYS:
        session.pop(key, None)


def get_config(request: Request) -> Config:
    return request.app.state.config


def get_logger(request: Request):
    return request.app.state.logger


def get_emby_client(request: Request) -> EmbyClient:
    return request.app.state.emby_client


def get_party_manager(request: Request) -> PartyManager:
    return request.app.state.party_manager


def get_token_manager(request: Request) -> HLSTokenManager:
    return request.app.state.token_manager


def get_stream_builder(request: Request) -> StreamBuilder:
    return request.app.state.stream_builder


def get_sio(request: Request):
    """Return the python-socketio AsyncServer so HTTP routes can emit."""
    return request.app.state.sio


def get_avatar_store(request: Request) -> AvatarStore:
    return request.app.state.avatar_store


def get_admin_session_store(request: Request) -> AdminSessionStore:
    return request.app.state.admin_session_store


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_emby_gateway(request: Request) -> EmbyGateway:
    return request.app.state.emby_gateway


# =============================================================================
# Party-bound session gates
# =============================================================================


@dataclass
class PartySession:
    """A resolved party-bound caller for the current request.

    Carries the cookie's `party_id` / `client_id` / `display_name` plus a
    live reference to the party dict so route handlers do not have to
    re-look it up.
    """

    party_id: str
    client_id: str
    display_name: str
    host_session_grant: str | None
    party: Party


def party_host_session_matches(
    party: Party,
    client_id: str | None,
    session_grant: str | None,
) -> bool:
    """Match the current host using an opaque grant, never public client_id alone."""
    if (
        not client_id
        or not session_grant
        or not party.host_client_id
        or not party.host_session_grant
        or client_id != party.host_client_id
    ):
        return False
    return secrets.compare_digest(session_grant, party.host_session_grant)


def require_party_session(
    request: Request,
    party_manager: PartyManager = Depends(get_party_manager),
) -> PartySession:
    """Require a valid party-bound session cookie.

    Cookie must carry `party_id` and `client_id`, and the party must
    still exist. Stale cookies referencing a deleted party are cleared
    and the request rejected with 404.
    """
    session = request.session
    scrub_legacy_admin_session(session)
    party_id = session.get("party_id")
    client_id = session.get("client_id")
    display_name = session.get("display_name", "")
    if not party_id or not client_id:
        raise HTTPException(status_code=401, detail="No party session")
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        session.pop("party_id", None)
        session.pop("client_id", None)
        session.pop("display_name", None)
        raise HTTPException(status_code=404, detail="Party no longer exists")
    return PartySession(
        party_id=party_id,
        client_id=client_id,
        display_name=display_name,
        host_session_grant=session.get("host_session_grant"),
        party=party,
    )


def require_party_unlocked(
    party_session: PartySession = Depends(require_party_session),
    party_manager: PartyManager = Depends(get_party_manager),
) -> PartySession:
    """Require require_party_session AND the party to be in UNLOCKED state.

    Use this for browse / search / item-details / select / change-streams
    where the host's Emby ACL must be currently active. Returns 423 Locked
    when the party has no host or the host has left.
    """
    if not party_manager.is_unlocked(party_session.party_id):
        raise HTTPException(status_code=423, detail="Party has no host")
    return party_session


def require_host_token(
    party_session: PartySession = Depends(require_party_session),
    party_manager: PartyManager = Depends(get_party_manager),
) -> PartySession:
    """Require any usable host token (UNLOCKED *or* PLAYING-ONLY).

    Use this for HLS / image / subtitle / intro routes that must keep
    serving the in-flight video even after the host disconnects, until
    the video ends naturally. Returns 423 Locked once the token has
    been cleared.
    """
    if not party_manager.has_host_token(party_session.party_id):
        raise HTTPException(status_code=423, detail="Party token has expired")
    return party_session


def require_admin(
    party_session: PartySession = Depends(require_party_session),
) -> PartySession:
    """Require the caller to be the party's host AND an Emby administrator.

    Admin is a sub-grant of host: the caller must be inside a party,
    must be that party's current host, and that host must have logged
    in with an Emby account that has `IsAdministrator=true`.
    """
    party = party_session.party
    if not party_host_session_matches(
        party,
        party_session.client_id,
        party_session.host_session_grant,
    ):
        raise HTTPException(status_code=403, detail="Host only")
    if not party.host_is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return party_session


def is_admin_authenticated(
    request: Request,
    party_manager: PartyManager,
    admin_session_store: AdminSessionStore | None = None,
) -> bool:
    """True if the caller is allowed into /admin via either path.

    Two ways in:
    1. Caller is the host of a party, and that host has Emby admin
       policy (`host_is_admin=True`). No separate /admin login needed.
    2. Legacy: caller did the standalone /api/admin/login flow which
       set `admin_authenticated` on the session. Kept so an admin can
       edit config without being in a party.
    """
    session = request.session
    if admin_session_store and admin_session_store.get(session.get("admin_session_id")):
        return True

    party_id = session.get("party_id")
    client_id = session.get("client_id")
    if not party_id or not client_id:
        return False
    party = party_manager.get(party_id.upper())
    if not party:
        return False
    return party_host_session_matches(
        party,
        client_id,
        session.get("host_session_grant"),
    ) and bool(party.host_is_admin)


def admin_display_name(
    request: Request,
    party_manager: PartyManager,
    admin_session_store: AdminSessionStore | None = None,
) -> str | None:
    """Return the name to log against an admin action, or None.

    Prefers the party-host identity when both paths are active; falls
    back to the legacy `admin_username` from the standalone flow.
    """
    session = request.session
    party_id = session.get("party_id")
    client_id = session.get("client_id")
    if party_id and client_id:
        party = party_manager.get(party_id.upper())
        if (
            party
            and party_host_session_matches(
                party,
                client_id,
                session.get("host_session_grant"),
            )
            and party.host_is_admin
        ):
            return party.host_username
    if admin_session_store:
        admin_session = admin_session_store.get(session.get("admin_session_id"))
        if admin_session:
            return admin_session.username
    return None


# =============================================================================
# Shared `responses={}` dicts for OpenAPI docs
# =============================================================================
#
# FastAPI's `responses={code: {...}}` decorator arg populates the
# OpenAPI spec so consumers see every status code an endpoint can
# return, not just the 200 path. Grouped here so the same gate ->
# same declared responses everywhere.

# Routes gated by `require_party_session` alone -- must have a cookie
# and the party must still exist. No host requirement.
PARTY_SESSION_RESPONSES: dict = {
    401: {"description": "No party-bound session cookie"},
    404: {"description": "Party no longer exists"},
}

# Routes gated by `require_party_unlocked` -- must have a cookie AND
# the party must currently have a host whose Emby ACL is active.
PARTY_UNLOCKED_RESPONSES: dict = {
    401: {"description": "No party-bound session cookie"},
    404: {"description": "Party no longer exists"},
    423: {"description": "Party has no host (LOCKED)"},
}

# Routes gated by `require_host_token` -- must have a cookie AND the
# party must still have a usable host token (UNLOCKED *or* PLAYING-ONLY).
PARTY_HOST_TOKEN_RESPONSES: dict = {
    401: {"description": "No party-bound session cookie"},
    404: {"description": "Party no longer exists"},
    423: {"description": "Party token has expired"},
}

# Admin gate -- host+admin, or standalone-admin session.
PARTY_ADMIN_RESPONSES: dict = {
    401: {"description": "No party-bound session cookie"},
    403: {"description": "Not the host or host is not an Emby admin"},
    404: {"description": "Party no longer exists"},
}
