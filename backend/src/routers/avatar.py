"""
Avatar Router -- passwordless chat avatars.

Three creation flows:
  POST /api/avatar/upload   -- multipart image bytes
  POST /api/avatar/gravatar -- email -> deterministic gravatar
  POST /api/avatar/recover  -- recovery code -> existing uuid

Serving:
  GET  /api/avatar/{uuid}              -- the user's avatar
  GET  /api/avatar/host/{party_id}     -- proxies the current host's
                                          Emby Primary image

See docs/AVATAR_TODO.md.
"""

import asyncio
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.src.dependencies import (
    get_avatar_store,
    get_config,
    get_emby_client,
    get_logger,
    get_party_manager,
)

router = APIRouter(prefix="/api/avatar", tags=["avatar"])


# =============================================================================
# Schemas
# =============================================================================

class GravatarRequest(BaseModel):
    email: str


class RecoverRequest(BaseModel):
    code: str


class AvatarCreatedResponse(BaseModel):
    """Returned from upload / gravatar.

    `code` is the plaintext recovery code -- shown to the user once
    and never returned by any other endpoint.
    """
    success: bool
    uuid: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None


class RecoverResponse(BaseModel):
    success: bool
    uuid: Optional[str] = None
    message: Optional[str] = None


# =============================================================================
# Rate limiting for /recover
# =============================================================================

_RECOVER_BUCKETS: dict[str, list[float]] = {}
_RECOVER_MAX = 10  # attempts per window
_RECOVER_WINDOW = 3600.0  # 1 hour


def _check_recover_rate(ip: str) -> bool:
    """Allow at most _RECOVER_MAX recover attempts per IP per window.

    Trivial fixed-window sliding implementation suitable for the MVP;
    swap out for slowapi if the dedicated rate limiter wires in later.
    """
    now = time.monotonic()
    bucket = _RECOVER_BUCKETS.get(ip, [])
    bucket = [t for t in bucket if now - t < _RECOVER_WINDOW]
    if len(bucket) >= _RECOVER_MAX:
        _RECOVER_BUCKETS[ip] = bucket
        return False
    bucket.append(now)
    _RECOVER_BUCKETS[ip] = bucket
    return True


# =============================================================================
# Upload constants
# =============================================================================

_MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB
_ALLOWED_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


# =============================================================================
# Routes
# =============================================================================

@router.post("/upload", response_model=AvatarCreatedResponse)
async def upload_avatar(
    request: Request,
    image: UploadFile = File(...),
    store=Depends(get_avatar_store),
    logger=Depends(get_logger),
):
    """Save an uploaded image and return a new uuid + recovery code."""
    mime = (image.content_type or "").lower()
    if mime not in _ALLOWED_MIME:
        return AvatarCreatedResponse(
            success=False,
            message=f"Unsupported image type: {mime or 'unknown'}",
        )

    data = await image.read()
    if not data:
        return AvatarCreatedResponse(success=False, message="Empty upload")
    if len(data) > _MAX_UPLOAD_BYTES:
        return AvatarCreatedResponse(
            success=False,
            message=f"Image too large (max {_MAX_UPLOAD_BYTES // 1024} KB)",
        )

    ext = _ALLOWED_MIME[mime]
    try:
        avatar_uuid, code = store.create_uploaded(data, ext)
    except Exception as e:
        logger.error(f"Avatar upload failed: {e}")
        return AvatarCreatedResponse(success=False, message="Could not save image")

    return AvatarCreatedResponse(success=True, uuid=avatar_uuid, code=code)


@router.post("/gravatar", response_model=AvatarCreatedResponse)
def create_gravatar(
    body: GravatarRequest,
    store=Depends(get_avatar_store),
    logger=Depends(get_logger),
):
    """Register a Gravatar association. Email is hashed before storage."""
    email = (body.email or "").strip()
    if "@" not in email or len(email) < 3:
        return AvatarCreatedResponse(success=False, message="Enter a valid email")
    try:
        avatar_uuid, code = store.create_gravatar(email)
    except Exception as e:
        logger.error(f"Gravatar avatar creation failed: {e}")
        return AvatarCreatedResponse(success=False, message="Could not register")
    return AvatarCreatedResponse(success=True, uuid=avatar_uuid, code=code)


@router.post("/recover", response_model=RecoverResponse)
def recover(
    body: RecoverRequest,
    request: Request,
    store=Depends(get_avatar_store),
    logger=Depends(get_logger),
):
    """Trade a recovery code for the avatar uuid it unlocks."""
    ip = (request.client.host if request.client else "unknown")
    if not _check_recover_rate(ip):
        logger.warning(f"Avatar recover rate-limited for ip={ip}")
        raise HTTPException(
            status_code=429,
            detail="Too many recovery attempts. Try again later.",
        )

    code = (body.code or "").strip().lower()
    if not code:
        return RecoverResponse(success=False, message="No code provided")

    avatar_uuid = store.recover_by_code(code)
    if not avatar_uuid:
        return RecoverResponse(success=False, message="Code not recognised")
    return RecoverResponse(success=True, uuid=avatar_uuid)


@router.get(
    "/host/{party_id}",
    responses={
        200: {
            "content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}},
            "description": "The current host's Emby Primary image",
        },
        404: {"description": "Party has no host, host has no Emby Primary, or party is unknown"},
    },
)
async def host_avatar(
    party_id: str,
    request: Request,
    config=Depends(get_config),
    emby_client=Depends(get_emby_client),
    party_manager=Depends(get_party_manager),
    logger=Depends(get_logger),
):
    """Proxy the current host's Emby Primary image for `party_id`.

    Returns 404 when the party has no host or the host has no Emby
    Primary image set. Uses the stored host access_token so the call
    inherits the host's ACL.
    """
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        return Response(status_code=404)
    host_user_id = party.get("host_user_id")
    host_token = party.get("host_access_token")
    if not host_user_id or not host_token:
        return Response(status_code=404)
    url = f"{config.EMBY_SERVER_URL}/emby/Users/{host_user_id}/Images/Primary"
    headers = emby_client._headers(host_token, host_user_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return Response(status_code=404)
        ct = resp.headers.get("Content-Type", "image/jpeg")
        if not ct.startswith("image/"):
            ct = "image/jpeg"
        return Response(
            content=resp.content,
            media_type=ct,
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as e:
        logger.warning(f"Host avatar proxy failed for {party_id}: {e}")
        return Response(status_code=404)


@router.get(
    "/{avatar_uuid}",
    responses={
        200: {
            "content": {
                "image/jpeg": {}, "image/png": {},
                "image/webp": {}, "image/gif": {},
            },
            "description": "Avatar image bytes (local file or Gravatar proxy)",
        },
        404: {"description": "Unknown avatar uuid or upstream fetch failed"},
    },
)
async def serve_avatar(
    avatar_uuid: str,
    store=Depends(get_avatar_store),
    logger=Depends(get_logger),
):
    """Return the avatar image referenced by `avatar_uuid`.

    `uploaded` rows serve the local file. `gravatar` rows are proxied
    from gravatar.com (so the caller's IP never reaches Gravatar).
    """
    row = store.get(avatar_uuid)
    if not row:
        return Response(status_code=404)
    # Best-effort: keep the entry alive on the cleanup clock.
    try:
        await asyncio.to_thread(store.touch, avatar_uuid)
    except Exception:
        pass

    if row["type"] == "uploaded":
        path = store.avatars_dir / Path(row["avatar_path"]).name
        if not path.exists():
            return Response(status_code=404)
        data = path.read_bytes()
        ext = path.suffix.lstrip(".").lower()
        media_type = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp", "gif": "image/gif",
        }.get(ext, "application/octet-stream")
        return Response(
            content=data,
            media_type=media_type,
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )

    if row["type"] == "gravatar":
        gh = row["gravatar_hash"]
        url = f"https://www.gravatar.com/avatar/{gh}?d=identicon&s=128"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return Response(status_code=404)
            return Response(
                content=resp.content,
                media_type=resp.headers.get("Content-Type", "image/jpeg"),
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except Exception as e:
            logger.warning(f"Gravatar proxy failed for {avatar_uuid[:8]}: {e}")
            return Response(status_code=404)

    return Response(status_code=404)
