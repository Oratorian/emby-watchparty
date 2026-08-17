"""Canonical FastAPI route surface used by runtime and schema generation."""

from backend.src.routers import admin, auth, avatar, health, hls, party, quality, v2

API_ROUTERS = (
    v2.router,
    auth.router,
    hls.router,
    party.router,
    admin.router,
    avatar.router,
    health.router,
    quality.router,
)

__all__ = ["API_ROUTERS"]
