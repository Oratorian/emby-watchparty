"""Canonical FastAPI route surface used by runtime and schema generation."""

from backend.src.routers import (
    admin,
    auth,
    avatar,
    health,
    hls,
    languages,
    party,
    previews,
    quality,
    v2,
)

API_ROUTERS = (
    v2.router,
    previews.router,
    auth.router,
    hls.router,
    party.router,
    admin.router,
    avatar.router,
    health.router,
    quality.router,
    languages.router,
    languages.admin_router,
)

__all__ = ["API_ROUTERS"]
