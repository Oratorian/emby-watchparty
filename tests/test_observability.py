import asyncio
import logging

import httpx
from fastapi import FastAPI

from backend.src.observability import RequestLogMiddleware
from tests.support.asgi import asgi_client


def test_route_log_has_context_without_sensitive_query_values(caplog):
    app = FastAPI()
    logger = logging.getLogger("test-observability")
    app.state.logger = logger
    app.add_middleware(RequestLogMiddleware)

    @app.get("/api/example")
    def example():
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger=logger.name):

        async def exercise() -> httpx.Response:
            async with asgi_client(app) as client:
                return await client.get(
                    "/api/example?token=complete-secret-token&recovery_code=secret-code"
                )

        response = asyncio.run(exercise())

    assert response.status_code == 200
    record = caplog.messages[-1]
    assert "route=/api/example" in record
    assert "latency_ms=" in record
    assert "outcome=200" in record
    assert "complete-secret-token" not in record
    assert "secret-code" not in record
