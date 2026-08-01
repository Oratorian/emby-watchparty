import asyncio
from unittest.mock import AsyncMock

import socketio

from backend.src.socket_protocol import install_inbound_validation


def test_invalid_socket_payload_uses_existing_error_event():
    sio = socketio.AsyncServer(async_mode="asgi")
    called = []

    @sio.on("seek")
    async def seek(_sid, data):
        called.append(data)

    sio.emit = AsyncMock()
    install_inbound_validation(sio)

    asyncio.run(sio.handlers["/"]["seek"]("sid-1", {"party_id": "PARTY"}))

    assert called == []
    sio.emit.assert_awaited_once()
    args, kwargs = sio.emit.await_args
    assert args[0] == "error"
    assert "Invalid seek payload" in args[1]["message"]
    assert kwargs == {"to": "sid-1"}


def test_unknown_socket_fields_remain_compatible():
    sio = socketio.AsyncServer(async_mode="asgi")
    called = []

    @sio.on("seek")
    async def seek(_sid, data):
        called.append(data)

    install_inbound_validation(sio)
    payload = {"party_id": "PARTY", "time": 12.5, "future_field": True}
    asyncio.run(sio.handlers["/"]["seek"]("sid-1", payload))

    assert called == [payload]
