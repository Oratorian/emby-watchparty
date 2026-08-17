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


def test_high_volume_and_health_routes_log_at_debug(caplog):
    app = FastAPI()
    logger = logging.getLogger("test-observability-quiet")
    app.state.logger = logger
    app.add_middleware(RequestLogMiddleware)

    # Every one of these is polled, streamed, or fetched per page load.
    # /api/party/list is the pointed case: its handler already logs at
    # DEBUG and documents why, while the middleware logged the same
    # request at INFO.
    quiet = (
        "/hls/segment.ts",
        "/socket.io/?EIO=4&transport=polling",
        "/assets/index-abc123.js",
        "/api/health",
        "/api/ready",
        "/api/party/list",
    )
    for path in quiet:
        app.add_api_route(path.split("?")[0], lambda: {"ok": True}, methods=["GET"])

    with caplog.at_level(logging.DEBUG, logger=logger.name):

        async def exercise() -> None:
            async with asgi_client(app) as client:
                for path in quiet:
                    await client.get(path)

        asyncio.run(exercise())

    assert len(caplog.records) == len(quiet)
    for record, path in zip(caplog.records, quiet, strict=True):
        assert record.levelno == logging.DEBUG, f"{path} still logs at INFO"


def test_prefixed_deployments_are_also_quiet(caplog):
    """APP_PREFIX must not reintroduce the volume.

    The match is by fragment and suffix rather than exact path precisely
    so a deployment mounted under /watchparty behaves the same.
    """
    app = FastAPI()
    logger = logging.getLogger("test-observability-prefixed")
    app.state.logger = logger
    app.add_middleware(RequestLogMiddleware)

    for path in ("/watchparty/hls/segment.ts", "/watchparty/api/party/list"):
        app.add_api_route(path, lambda: {"ok": True}, methods=["GET"])

    with caplog.at_level(logging.DEBUG, logger=logger.name):

        async def exercise() -> None:
            async with asgi_client(app) as client:
                await client.get("/watchparty/hls/segment.ts")
                await client.get("/watchparty/api/party/list")

        asyncio.run(exercise())

    assert all(record.levelno == logging.DEBUG for record in caplog.records)


def test_ordinary_routes_still_log_at_info(caplog):
    """The exclusions must stay narrow; this is the regression guard."""
    app = FastAPI()
    logger = logging.getLogger("test-observability-loud")
    app.state.logger = logger
    app.add_middleware(RequestLogMiddleware)

    for path in ("/api/party/create", "/api/v2/auth/login", "/api/admin/config"):
        app.add_api_route(path, lambda: {"ok": True}, methods=["GET"])

    with caplog.at_level(logging.DEBUG, logger=logger.name):

        async def exercise() -> None:
            async with asgi_client(app) as client:
                for path in ("/api/party/create", "/api/v2/auth/login", "/api/admin/config"):
                    await client.get(path)

        asyncio.run(exercise())

    assert len(caplog.records) == 3
    assert all(record.levelno == logging.INFO for record in caplog.records)
