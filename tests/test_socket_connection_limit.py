import asyncio

import pytest
from socketio.exceptions import ConnectionRefusedError

from backend.src.rate_limit import SlidingWindowRateLimiter
from backend.src.socket_handlers.connection import register


class _Sio:
    def __init__(self):
        self.handlers = {}

    def event(self, function):
        self.handlers[function.__name__] = function
        return function

    async def emit(self, *_args, **_kwargs):
        return None


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class _Parties:
    def exists(self, _party_id):
        return False


def test_socket_connection_attempts_return_rate_limited_reason():
    sio = _Sio()
    register({
        "sio": sio,
        "emby_client": object(),
        "logger": _Logger(),
        "party_manager": _Parties(),
        "session_secret": None,
        "rate_limiter": SlidingWindowRateLimiter(),
        "config": type("Config", (), {
            "TRUSTED_PROXY_CIDRS": (),
            "ENABLE_RATE_LIMITING": True,
            "RATE_LIMIT_SOCKET_CONNECTIONS": "1 per minute",
        })(),
    })

    environ = {"REMOTE_ADDR": "203.0.113.10"}
    asyncio.run(sio.handlers["connect"]("sid-1", environ))
    with pytest.raises(ConnectionRefusedError, match="rate_limited"):
        asyncio.run(sio.handlers["connect"]("sid-2", environ))
