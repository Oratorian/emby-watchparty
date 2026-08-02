from __future__ import annotations

import asyncio
from time import perf_counter
from urllib.parse import urljoin

import httpx
import socketio


def _media_line(playlist: str) -> str:
    return next(line for line in playlist.splitlines() if line and not line.startswith("#"))


async def _select_video(base_url: str) -> tuple[httpx.AsyncClient, socketio.AsyncClient, str]:
    client = httpx.AsyncClient(base_url=base_url)
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "client-1", "display_name": "Alice"},
    )
    authenticated = await client.post(
        "/api/auth/login", json={"username": "Alice", "password": "password"}
    )
    assert authenticated.json()["success"] is True

    selected = asyncio.Event()
    stream_url = ""
    realtime = socketio.AsyncClient()

    @realtime.on("video_selected")
    async def on_video_selected(data):
        nonlocal stream_url
        stream_url = data["video"]["stream_url"]
        selected.set()

    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    await realtime.connect(base_url, headers={"Cookie": cookie})
    await realtime.emit(
        "join_party",
        {"party_id": party_id, "username": "Alice", "client_id": "client-1"},
    )
    await realtime.emit(
        "select_video",
        {"party_id": party_id, "item_id": "movie-1", "item_name": "Fake Movie"},
    )
    await asyncio.wait_for(selected.wait(), timeout=5)
    return client, realtime, stream_url


async def _exercise_streaming_and_range(live_watchparty) -> None:
    await httpx.AsyncClient().post(
        f"{live_watchparty.fake.url}/__test__/behavior",
        json={"segment_delay_ms": 300},
    )
    client, realtime, master_url = await _select_video(live_watchparty.url)
    try:
        master = await client.get(master_url)
        assert master.status_code == 200
        variant_url = urljoin(master_url, _media_line(master.text))
        variant = await client.get(variant_url)
        assert variant.status_code == 200
        segment_url = urljoin(variant_url, _media_line(variant.text))

        started = perf_counter()
        async with client.stream("GET", segment_url) as response:
            chunks = response.aiter_bytes()
            first = await anext(chunks)
            first_elapsed = perf_counter() - started
            remainder = b"".join([chunk async for chunk in chunks])
        total_elapsed = perf_counter() - started

        assert first
        assert remainder
        assert first_elapsed < 0.2
        assert total_elapsed >= 0.25

        ranged = await client.get(segment_url, headers={"Range": "bytes=0-17"})
        assert ranged.status_code == 206
        assert ranged.headers["content-range"] == "bytes 0-17/36"
        assert ranged.headers["accept-ranges"] == "bytes"
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_live_hls_streams_first_chunk_and_forwards_ios_range(live_watchparty) -> None:
    asyncio.run(_exercise_streaming_and_range(live_watchparty))


async def _exercise_disconnect_closes_upstream(live_watchparty) -> None:
    async with httpx.AsyncClient() as controls:
        await controls.post(f"{live_watchparty.fake.url}/__test__/reset")
        await controls.post(
            f"{live_watchparty.fake.url}/__test__/behavior",
            json={"segment_delay_ms": 1000},
        )
    client, realtime, master_url = await _select_video(live_watchparty.url)
    try:
        master = await client.get(master_url)
        variant_url = urljoin(master_url, _media_line(master.text))
        variant = await client.get(variant_url)
        segment_url = urljoin(variant_url, _media_line(variant.text))

        async with client.stream("GET", segment_url) as response:
            await anext(response.aiter_bytes())

        async with httpx.AsyncClient() as controls:
            for _ in range(50):
                state = await controls.get(f"{live_watchparty.fake.url}/__test__/state")
                if state.status_code == 200 and state.json()["stream_closed"]:
                    break
                await asyncio.sleep(0.02)
            else:
                raise AssertionError("upstream HLS stream remained open after disconnect")
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_live_hls_disconnect_closes_upstream(live_watchparty) -> None:
    asyncio.run(_exercise_disconnect_closes_upstream(live_watchparty))
