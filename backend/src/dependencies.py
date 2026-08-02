"""
FastAPI dependency injection
Replaces the old Flask deps dict pattern.

Plus the party-bound session gates used to protect every route that
touches Emby on behalf of a watch party.
"""

import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request

from backend.src.config import Config
from backend.src.emby_client import EmbyClient
from backend.src.party_manager import PartyManager
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.stream_builder import StreamBuilder
from backend.src.avatar_store import AvatarStore
from backend.src.admin_session_store import AdminSessionStore


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
    party: dict
    # The host's server-issued proof, present only in the real host's
    # cookie. None for ordinary members. See _owns_host_identity.
    host_session_grant: Optional[str] = None


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
        party=party,
        host_session_grant=session.get("host_session_grant"),
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


def _owns_host_identity(party: dict, client_id: Optional[str],
                        grant: Optional[str]) -> bool:
    """True only when the caller can PROVE they are the party's host.

    `client_id` is not proof. It is broadcast to every party member in
    the `host_changed` event, and `POST /api/party/<id>/join` stores a
    caller-supplied `client_id` verbatim, so any attendee could scrape
    the host's id, re-join supplying it, and receive a validly signed
    cookie carrying the host's identity. Matching on client_id alone
    therefore handed admin rights to anyone in the room whenever the
    host's Emby account had `IsAdministrator=true`.

    `host_session_grant` is minted server-side by `set_host` and only
    ever written to the real host's cookie, so it cannot be scraped from
    any broadcast. Compared with `compare_digest` to avoid leaking a
    match position through timing.
    """
    expected = party.get("host_session_grant")
    if not expected or not grant or not client_id:
        return False
    if party.get("host_client_id") != client_id:
        return False
    return secrets.compare_digest(str(grant), str(expected))


def require_admin(
    party_session: PartySession = Depends(require_party_session),
) -> PartySession:
    """Require the caller to be the party's host AND an Emby administrator.

    Admin is a sub-grant of host: the caller must be inside a party,
    must prove they are that party's current host, and that host must
    have logged in with an Emby account that has `IsAdministrator=true`.
    """
    party = party_session.party
    if not _owns_host_identity(
        party, party_session.client_id, party_session.host_session_grant
    ):
        raise HTTPException(status_code=403, detail="Host only")
    if not party.get("host_is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return party_session


def is_admin_authenticated(request: Request, party_manager: PartyManager) -> bool:
    """True if the caller is allowed into /admin via either path.

    Two ways in:
    1. Caller is the host of a party, and that host has Emby admin
       policy (`host_is_admin=True`). No separate /admin login needed.
    2. Legacy: caller did the standalone /api/admin/login flow which
       set `admin_authenticated` on the session. Kept so an admin can
       edit config without being in a party.
    """
    session = request.session
    if session.get("admin_authenticated"):
        return True

    party_id = session.get("party_id")
    client_id = session.get("client_id")
    if not party_id or not client_id:
        return False
    party = party_manager.get(party_id.upper())
    if not party:
        return False
    return (
        _owns_host_identity(party, client_id, session.get("host_session_grant"))
        and bool(party.get("host_is_admin"))
    )


def admin_display_name(request: Request, party_manager: PartyManager) -> Optional[str]:
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
            and _owns_host_identity(
                party, client_id, session.get("host_session_grant")
            )
            and party.get("host_is_admin")
        ):
            return party.get("host_username")
    return session.get("admin_username")


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
