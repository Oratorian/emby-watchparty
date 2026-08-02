import asyncio
from time import perf_counter

import httpx
import socketio


async def _exercise_independent_controls(live_watchparty) -> None:
    client = httpx.AsyncClient(base_url=live_watchparty.url)
    controls = httpx.AsyncClient(base_url=live_watchparty.fake.url)
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "client-1", "display_name": "Alice"},
    )
    await client.post(
        "/api/auth/login", json={"username": "Alice", "password": "password"}
    )
    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    realtime = socketio.AsyncClient()
    selected = asyncio.Event()

    @realtime.on("video_selected")
    async def video_selected(_data):
        selected.set()

    await realtime.connect(live_watchparty.url, headers={"Cookie": cookie})
    try:
        await realtime.emit(
            "join_party",
            {"party_id": party_id, "username": "Alice", "client_id": "client-1"},
        )
        await realtime.emit(
            "select_video",
            {"party_id": party_id, "item_id": "movie-1", "item_name": "Fake Movie"},
        )
        await asyncio.wait_for(selected.wait(), timeout=5)
        await controls.post(
            "/__test__/behavior",
            json={"delays_ms": {"/emby/Sessions/Playing/Progress": 500}},
        )

        pause_received = asyncio.Event()

        @realtime.on("pause")
        async def paused(_data):
            pause_received.set()

        started = perf_counter()
        await realtime.emit("play", {"party_id": party_id, "time": 1.0})
        await realtime.emit("pause", {"party_id": party_id, "time": 1.1})
        await asyncio.wait_for(pause_received.wait(), timeout=0.25)
        assert perf_counter() - started < 0.25
        for _ in range(30):
            recorded = (await controls.get("/__test__/requests")).json()["requests"]
            if any(
                row["path"] == "/emby/Sessions/Playing/Progress"
                for row in recorded
            ):
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("playback progress was not reported to Emby")
    finally:
        await realtime.disconnect()
        await client.aclose()
        await controls.aclose()


def test_slow_emby_progress_does_not_block_independent_socket_control(
    live_watchparty,
) -> None:
    asyncio.run(_exercise_independent_controls(live_watchparty))
