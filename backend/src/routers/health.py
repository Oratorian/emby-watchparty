"""
Health Router -- container liveness probe.

Anonymous. Returns 200 as long as the process can serve the request.
Does not depend on Emby, the avatar DB, or any other subsystem so a
transient outage upstream cannot cause a restart loop in Docker /
Kubernetes / a reverse-proxy healthcheck.

Readiness is exposed separately at `/api/ready`; Docker continues to
use liveness so an Emby outage cannot trigger a container restart loop.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.src import __version__, __codename__
from backend.src.dependencies import get_avatar_store, get_config, get_emby_gateway
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
    emby_gateway=Depends(get_emby_gateway),
    avatar_store=Depends(get_avatar_store),
):
    configured = bool(config.EMBY_SERVER_URL and config.EMBY_API_KEY)
    reachable = False
    if configured:
        try:
            response = await emby_gateway.get(
                "/emby/System/Info/Public",
                timeout=2.0,
            )
            reachable = response.status_code == 200
        except Exception:
            reachable = False

    checks = {
        "config": configured,
        "storage": avatar_store.readiness_check(),
        "emby": reachable,
    }
    is_ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )
