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


async def _exercise_foreign_playlist_rejection(live_watchparty) -> None:
    async with httpx.AsyncClient() as controls:
        await controls.post(
            f"{live_watchparty.fake.url}/__test__/behavior",
            json={
                "master_playlist": (
                    "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\n"
                    "https://foreign.invalid/steal.m3u8\n"
                )
            },
        )
    client, realtime, master_url = await _select_video(live_watchparty.url)
    try:
        response = await client.get(master_url)
        assert response.status_code == 502
        assert response.json() == {"error": "Unsafe upstream playlist"}
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_live_hls_rejects_foreign_playlist_urls(live_watchparty) -> None:
    asyncio.run(_exercise_foreign_playlist_rejection(live_watchparty))


async def _exercise_select_leave_race(live_watchparty) -> None:
    controls = httpx.AsyncClient(base_url=live_watchparty.fake.url)
    await controls.post(
        "/__test__/behavior",
        json={"delays_ms": {"/emby/Items/movie-1/PlaybackInfo": 400}},
    )
    client = httpx.AsyncClient(base_url=live_watchparty.url)
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "racing-client", "display_name": "Alice"},
    )
    await client.post(
        "/api/auth/login", json={"username": "Alice", "password": "password"}
    )
    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    realtime = socketio.AsyncClient()
    await realtime.connect(live_watchparty.url, headers={"Cookie": cookie})
    try:
        await realtime.emit(
            "join_party",
            {"party_id": party_id, "username": "Alice", "client_id": "racing-client"},
        )
        await realtime.emit(
            "select_video",
            {"party_id": party_id, "item_id": "movie-1", "item_name": "Fake Movie"},
        )
        for _ in range(100):
            recorded = (await controls.get("/__test__/requests")).json()["requests"]
            if any(row["path"].endswith("/PlaybackInfo") for row in recorded):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("selection never reached fake Emby")

        await realtime.emit("leave_party", {"party_id": party_id})
        await asyncio.sleep(0.7)

        exists = await client.get(f"/api/party/{party_id}/exists")
        assert exists.json() == {"exists": False}
        recorded = (await controls.get("/__test__/requests")).json()["requests"]
        assert any(
            row["method"] == "DELETE" and row["path"] == "/emby/Videos/ActiveEncodings"
            for row in recorded
        ), "obsolete transcode from stale selection was not cancelled"
    finally:
        if realtime.connected:
            await realtime.disconnect()
        await client.aclose()
        await controls.aclose()


def test_concurrent_select_and_leave_cancels_stale_transcode(live_watchparty) -> None:
    asyncio.run(_exercise_select_leave_race(live_watchparty))
