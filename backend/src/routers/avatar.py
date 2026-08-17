"""
Avatar Router -- passwordless chat avatars.

Three creation flows:
  POST /api/avatar/upload   -- multipart image bytes
  POST /api/avatar/gravatar -- email -> deterministic gravatar
  POST /api/avatar/recover  -- recovery code -> existing uuid

Serving:
  GET  /api/avatar/{uuid}              -- the user's avatar
  GET  /api/avatar/host/{party_id}     -- proxies the current host's
                                          media-server Primary image
"""

import asyncio
import contextlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.src.client_ip import request_client_ip
from backend.src.dependencies import (
    get_avatar_store,
    get_http_client,
    get_logger,
    get_media_server,
    get_party_manager,
)
from backend.src.providers.models import AssetRequest, ProviderCredentials
from backend.src.rate_limit import parse_rate, rate_limit_response

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
    uuid: str | None = None
    code: str | None = None
    message: str | None = None


class RecoverResponse(BaseModel):
    success: bool
    uuid: str | None = None
    message: str | None = None


# =============================================================================
# Rate limiting for /recover
# =============================================================================

_RECOVER_MAX = 10  # attempts per window
_RECOVER_WINDOW = 3600  # 1 hour


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
    _request: Request,
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
        logger.error("Avatar upload failed: error=%s", type(e).__name__)
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
        logger.error("Gravatar avatar creation failed: error=%s", type(e).__name__)
        return AvatarCreatedResponse(success=False, message="Could not register")
    return AvatarCreatedResponse(success=True, uuid=avatar_uuid, code=code)


@router.post(
    "/recover",
    response_model=RecoverResponse,
    responses={
        429: {"description": "Rate-limited (10 attempts per IP per hour)"},
    },
)
def recover(
    body: RecoverRequest,
    request: Request,
    store=Depends(get_avatar_store),
    logger=Depends(get_logger),
):
    """Trade a recovery code for the avatar uuid it unlocks."""
    config = request.app.state.config
    if config.ENABLE_RATE_LIMITING:
        ip = request_client_ip(request, config.TRUSTED_PROXY_CIDRS)
        limit, window = parse_rate(getattr(config, "RATE_LIMIT_AVATAR_RECOVERY", "10 per hour"))
        decision = request.app.state.rate_limiter.check(f"avatar-recover:{ip}", limit, window)
        if not decision.allowed:
            logger.warning(f"Avatar recover rate-limited for ip={ip}")
            return rate_limit_response("avatar recovery attempts", decision.retry_after)

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
            "description": "The current host's media-server Primary image",
        },
        404: {"description": "Party has no host, host has no Primary image, or party is unknown"},
    },
)
async def host_avatar(
    party_id: str,
    _request: Request,
    provider=Depends(get_media_server),
    party_manager=Depends(get_party_manager),
    logger=Depends(get_logger),
):
    """Proxy the current host's media-server Primary image for `party_id`.

    Returns 404 when the party has no host or the host has no Primary
    image set. Uses the stored host access_token so the call inherits
    the host's ACL.
    """
    party_id = party_id.upper()
    party = party_manager.get(party_id)
    if not party:
        return Response(status_code=404)
    host_user_id = party.host_user_id
    host_token = party.host_access_token
    if not host_user_id or not host_token:
        return Response(status_code=404)
    try:
        resp = await provider.fetch_asset(
            AssetRequest(
                item_id=host_user_id,
                kind="avatar",
                credentials=ProviderCredentials(access_token=host_token, user_id=host_user_id),
            )
        )
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
        logger.warning(
            "Host avatar proxy failed party=%s error=%s",
            party_id,
            type(e).__name__,
        )
        return Response(status_code=404)


@router.get(
    "/{avatar_uuid}",
    responses={
        200: {
            "content": {
                "image/jpeg": {},
                "image/png": {},
                "image/webp": {},
                "image/gif": {},
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
    http_client=Depends(get_http_client),
):
    """Return the avatar image referenced by `avatar_uuid`.

    `uploaded` rows serve the local file. `gravatar` rows are proxied
    from gravatar.com (so the caller's IP never reaches Gravatar).
    """
    row = store.get(avatar_uuid)
    if not row:
        return Response(status_code=404)
    # Best-effort: keep the entry alive on the cleanup clock.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(store.touch, avatar_uuid)

    if row["type"] == "uploaded":
        path = store.avatars_dir / Path(row["avatar_path"]).name
        if not path.exists():
            return Response(status_code=404)
        data = path.read_bytes()
        ext = path.suffix.lstrip(".").lower()
        media_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "gif": "image/gif",
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
            resp = await http_client.get(url, timeout=10)
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
            logger.warning(
                "Gravatar proxy failed avatar=%s error=%s",
                avatar_uuid[:8],
                type(e).__name__,
            )
            return Response(status_code=404)

    return Response(status_code=404)
