import asyncio

import pytest
import socketio

from backend.src.socket_protocol import install_outbound_validation


def test_typed_emitter_rejects_invalid_nested_video_payload() -> None:
    sio = socketio.AsyncServer(async_mode="asgi")
    install_outbound_validation(sio)

    with pytest.raises(ValueError, match="video_selected"):
        asyncio.run(
            sio.emit(
                "video_selected",
                {"video": {"item_id": 123, "title": "Wrong item id type"}},
                to="sid-1",
            )
        )
