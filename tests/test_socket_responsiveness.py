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
    await client.post("/api/auth/login", json={"username": "Alice", "password": "password"})
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
            if any(row["path"] == "/emby/Sessions/Playing/Progress" for row in recorded):
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


async def _exercise_progress_coalescing(live_watchparty) -> None:
    async with httpx.AsyncClient(base_url=live_watchparty.url) as client:
        created = await client.post("/api/party/create", json={})
        party_id = created.json()["party_id"]
        await client.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "progress-client", "display_name": "Alice"},
        )
        await client.post("/api/auth/login", json={"username": "Alice", "password": "password"})
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
                {
                    "party_id": party_id,
                    "username": "Alice",
                    "client_id": "progress-client",
                },
            )
            await realtime.emit(
                "select_video",
                {"party_id": party_id, "item_id": "movie-1", "item_name": "Fake Movie"},
            )
            await asyncio.wait_for(selected.wait(), timeout=5)
            live_watchparty.fake.state.requests.clear()

            await realtime.emit("report_progress", {"party_id": party_id, "time": 12.0})
            await realtime.emit("report_progress", {"party_id": party_id, "time": 34.0})

            for _ in range(50):
                state = (await client.get(f"/api/party/{party_id}/info")).json()
                if state["playback_state"]["time"] == 34.0:
                    break
                await asyncio.sleep(0.02)
            assert state["playback_state"]["time"] == 34.0
            progress_reports = [
                request
                for request in live_watchparty.fake.state.requests
                if request["path"] == "/emby/Sessions/Playing/Progress"
            ]
            assert len(progress_reports) == 1
            # WHICH report survived, not just how many. The handler throttles
            # by dropping anything inside the window, so the report that
            # reaches Emby carries the FIRST position, 12.0s, while the party
            # state advances to 34.0s. Asserting only the count left
            # "drop the newer" and "coalesce to the latest" indistinguishable,
            # though they send different positions upstream.
            assert progress_reports[0]["body"]["PositionTicks"] == 120_000_000
        finally:
            await realtime.disconnect()


def test_limited_progress_commits_latest_party_time(live_watchparty) -> None:
    asyncio.run(_exercise_progress_coalescing(live_watchparty))
