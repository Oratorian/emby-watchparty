"""Structured, redacted request observability."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response


# Request lines that are noise rather than signal, dropped to DEBUG so the
# INFO stream stays readable. Matched as substring or suffix so an
# APP_PREFIX deployment is covered without rebuilding the list.
#
# Volume, worst first:
#   /hls/            several requests per second per viewer
#   /socket.io       the polling transport, before and instead of upgrade
#   /api/party/list  polled every ~5s per open index tab
#   /assets/         every file of the SPA bundle, per page load
#   health/ready     whatever the orchestrator's probe interval is
#
# /api/party/list is the pointed one: its handler already logs at DEBUG and
# says so, "this route is polled every ~5s per open index tab, so it
# deliberately stays at DEBUG (no INFO spam)". The middleware was emitting
# an INFO line for the same request and defeating that.
_QUIET_PATH_FRAGMENTS = ("/hls/", "/socket.io", "/assets/")
_QUIET_PATH_SUFFIXES = ("/api/health", "/api/ready", "/api/party/list")


def _is_quiet_path(path: str) -> bool:
    return any(fragment in path for fragment in _QUIET_PATH_FRAGMENTS) or path.endswith(
        _QUIET_PATH_SUFFIXES
    )


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        outcome: int | str = "error"
        try:
            response = await call_next(request)
            outcome = response.status_code
            return response
        finally:
            logger = getattr(request.app.state, "logger", None)
            if logger:
                session = request.scope.get("session") or {}
                party_id = session.get("party_id", "-")
                latency_ms = (perf_counter() - started) * 1000
                log = logger.debug if _is_quiet_path(request.url.path) else logger.info
                log(
                    "request route=%s method=%s party=%s latency_ms=%.1f outcome=%s retry=0",
                    request.url.path,
                    request.method,
                    party_id,
                    latency_ms,
                    outcome,
                )
