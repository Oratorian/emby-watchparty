"""
Party Router - Create and query parties
"""

from fastapi import APIRouter, Depends

from backend.src.dependencies import get_config, get_party_manager, get_logger
from backend.src.schemas import CreatePartyResponse, PartyInfoResponse

router = APIRouter(prefix="/api/party", tags=["party"])


@router.get("/static-session")
def static_session(config=Depends(get_config)):
    """Return static session ID if enabled, or null."""
    if config.STATIC_SESSION_ENABLED:
        return {"party_id": config.STATIC_SESSION_ID.upper()}
    return {"party_id": None}


@router.post("/create", response_model=CreatePartyResponse)
def create_party(config=Depends(get_config), party_manager=Depends(get_party_manager),
                 logger=Depends(get_logger)):
    party_id = party_manager.create_party()
    logger.info(f"Created new watch party: {party_id}")
    prefix = config.APP_PREFIX
    return CreatePartyResponse(party_id=party_id, url=f"{prefix}/party/{party_id}")


@router.get("/{party_id}/info", response_model=PartyInfoResponse)
def party_info(party_id: str, party_manager=Depends(get_party_manager)):
    party = party_manager.get(party_id.upper())
    if not party:
        return {"error": "Party not found"}
    return PartyInfoResponse(
        id=party["id"],
        users=list(party["users"].values()),
        current_video=party["current_video"],
        playback_state=party["playback_state"],
    )
