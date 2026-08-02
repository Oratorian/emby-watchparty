"""Structured, redacted request observability."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response


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
                logger.info(
                    "request route=%s method=%s party=%s latency_ms=%.1f outcome=%s retry=0",
                    request.url.path,
                    request.method,
                    party_id,
                    latency_ms,
                    outcome,
                )
