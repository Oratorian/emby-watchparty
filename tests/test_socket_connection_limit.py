import asyncio

import pytest
import socketio


async def _exhaust_public_socket_limit(base_url: str) -> object:
    for _ in range(30):
        accepted = socketio.AsyncClient()
        await accepted.connect(base_url)
        await accepted.disconnect()

    rejected = socketio.AsyncClient()
    reasons: list[object] = []

    @rejected.on("connect_error")
    async def connect_error(data: object) -> None:
        reasons.append(data)

    with pytest.raises(socketio.exceptions.ConnectionError):
        await rejected.connect(base_url)
    return reasons[0]


def test_socket_connection_attempts_return_rate_limited_reason(
    live_watchparty,
) -> None:
    reason = asyncio.run(_exhaust_public_socket_limit(live_watchparty.url))

    assert isinstance(reason, dict)
    retry_after = reason["data"]["retry_after"]
    assert retry_after > 0
    assert reason == {
        "message": f"Too many connection attempts. Try again in {retry_after} seconds.",
        "data": {"code": "rate_limited", "retry_after": retry_after},
    }
