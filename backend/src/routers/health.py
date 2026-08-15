"""
Health Router -- container liveness probe.

Anonymous. Returns 200 as long as the process can serve the request.
Does not depend on the media server, avatar DB, or any other subsystem so a
transient outage upstream cannot cause a restart loop in Docker /
Kubernetes / a reverse-proxy healthcheck.

Readiness is exposed separately at `/api/ready`; Docker continues to
use liveness so a media-server outage cannot trigger a container restart loop.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.src import __codename__, __version__
from backend.src.dependencies import get_avatar_store, get_config, get_media_server
from backend.src.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        version=__version__,
        codename=__codename__,
    )


@router.get("/ready")
async def ready(
    config=Depends(get_config),
    media_server=Depends(get_media_server),
    avatar_store=Depends(get_avatar_store),
):
    configured = bool(config.MEDIA_SERVER_URL and config.MEDIA_SERVER_API_KEY)
    reachable = credentials_valid = False
    if configured:
        try:
            provider_check = await media_server.readiness()
            reachable = provider_check.reachable
            credentials_valid = provider_check.credentials_valid
        except Exception:
            reachable = credentials_valid = False

    checks = {
        "config": configured,
        "storage": avatar_store.readiness_check(),
        "media_server_reachable": reachable,
        "media_server_credentials": credentials_valid,
    }
    if config.MEDIA_SERVER_TYPE == "emby":
        checks["emby"] = reachable
    is_ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )
