import asyncio
import unittest

from backend.src.socket_handlers import sync


class _Sio:
    def __init__(self):
        self.handlers = {}

    def on(self, event):
        def decorate(handler):
            self.handlers[event] = handler
            return handler
        return decorate

    async def emit(self, *_args, **_kwargs):
        pass


class _EmbyClient:
    async def report_playback_progress(self, **_kwargs):
        await asyncio.sleep(0.15)


class _PartyManager:
    def __init__(self):
        self.party = {
            "users": {"sid-1": "Alice"},
            "sid_client_ids": {"sid-1": "client-1"},
            "current_video": {"item_id": "item", "run_time_seconds": 60},
            "user_streams": {
                "sid-1": {
                    "play_session_id": "play-session",
                    "media_source_id": "source",
                }
            },
            "playback_state": {"playing": False, "time": 0, "last_update": ""},
            "host_access_token": "token",
            "host_user_id": "user",
            "ready_check": None,
        }

    def get(self, party_id):
        return self.party if party_id == "PARTY" else None


class _Logger:
    def debug(self, _message):
        pass

    def info(self, _message):
        pass


class SocketResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_emby_progress_does_not_block_event_loop(self):
        sio = _Sio()
        sync.register({
            "sio": sio,
            "emby_client": _EmbyClient(),
            "logger": _Logger(),
            "party_manager": _PartyManager(),
        })

        started = asyncio.get_running_loop().time()
        task = asyncio.create_task(sio.handlers["play"](
            "sid-1", {"party_id": "PARTY", "time": 12},
        ))
        await asyncio.sleep(0.01)
        elapsed = asyncio.get_running_loop().time() - started

        self.assertLess(elapsed, 0.08)
        self.assertFalse(task.done())
        await task


if __name__ == "__main__":
    unittest.main()
