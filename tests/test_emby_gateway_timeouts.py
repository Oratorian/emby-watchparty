"""Every upstream Emby request must be time-bounded.

An unbounded call pins a worker slot until the OS gives up on the socket,
which is the failure `_EMBY_HTTP_TIMEOUT` was introduced to prevent. The
subtlety is that httpx distinguishes "no timeout" from "use the client's
default", and the gateway conflated them.
"""

import asyncio
import logging

import httpx

from backend.src.emby_gateway import EmbyGateway

CLIENT_TIMEOUT = httpx.Timeout(30.0, connect=5.0, pool=5.0)


def _gateway_recording_timeouts() -> tuple[EmbyGateway, dict]:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.extensions.get("timeout") or {})
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=CLIENT_TIMEOUT)
    gateway = EmbyGateway(client, "http://emby.test", logging.getLogger("test-gateway"))
    return gateway, seen


def test_call_without_an_explicit_timeout_inherits_the_client_default():
    """`timeout=None` must mean "ask the client", not "wait forever".

    httpx reads an explicit None as every timeout disabled, so passing the
    parameter straight through overrode the client's configured Timeout and
    left twelve call sites in emby_client and the media router unbounded.
    """
    gateway, seen = _gateway_recording_timeouts()

    asyncio.run(gateway.get("/emby/Items"))

    assert seen["read"] == 30.0, f"read timeout was not bounded: {seen}"
    assert seen["connect"] == 5.0
    assert seen["pool"] == 5.0
    assert None not in seen.values(), f"a timeout dimension is disabled: {seen}"


def test_an_explicit_timeout_still_wins_over_the_client_default():
    gateway, seen = _gateway_recording_timeouts()

    asyncio.run(gateway.get("/emby/Items", timeout=2.5))

    assert seen["read"] == 2.5
    assert seen["connect"] == 2.5


def test_streamed_segments_are_bounded_too():
    """`open_stream` builds its request without naming a timeout.

    Omitting the argument is the correct spelling: httpx then applies the
    client default. This pins that, because the obvious "fix" of passing
    None here would silently unbound the highest-volume path in the app.
    """
    gateway, seen = _gateway_recording_timeouts()

    async def exercise() -> None:
        response = await gateway.open_stream("/emby/Videos/movie-1/segment0.ts")
        await response.aclose()

    asyncio.run(exercise())

    assert seen["read"] == 30.0
    assert seen["connect"] == 5.0
