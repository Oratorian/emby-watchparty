"""
Health Router -- container liveness probe.

Anonymous. Returns 200 as long as the process can serve the request.
Does not depend on Emby, the avatar DB, or any other subsystem so a
transient outage upstream cannot cause a restart loop in Docker /
Kubernetes / a reverse-proxy healthcheck.

For readiness checks that confirm Emby is reachable, add a separate
`/api/ready` endpoint later -- liveness and readiness are different
guarantees and conflating them is a common cause of cascading
failures.
"""

from fastapi import APIRouter

from backend.src import __version__, __codename__
from backend.src.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        version=__version__,
        codename=__codename__,
    )
