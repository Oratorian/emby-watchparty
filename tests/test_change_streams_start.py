"""The in-player version/track switch must ask Emby for a reachable position.

`clamp_start_seconds` is unit-tested next door, but a clamp that is not wired
into its call site is worth nothing, and nothing else in the suite emits
`change_streams`. These drive the real socket handler and read the start
offset back off the PlaybackInfo request the fake Emby actually received, so
unplugging the clamp -- or passing the raw party clock instead of the clamped
value -- fails here.

The failure it guards against is not local to the person switching: Emby
answers a start past the end of media with a zero-length manifest, the player
reports `ended` immediately, and from the selector that runs video_ended and
stops the film for the whole room.
"""

import asyncio

import httpx
import socketio

# tests/support/fake_emby.py MOVIE: 6e9 ticks = 600 seconds.
MOVIE_RUN_TIME_SECONDS = 600.0


async def _playing_host(base_url: str):
    """A host with a video selected, joined over both HTTP and the socket."""
    client = httpx.AsyncClient(base_url=base_url)
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "host-client", "display_name": "Host"},
    )
    login = await client.post("/api/auth/login", json={"username": "Host", "password": "password"})
    assert login.json()["success"] is True
    cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
    realtime = socketio.AsyncClient()
    await realtime.connect(base_url, headers={"Cookie": cookie})
    await realtime.emit(
        "join_party",
        {"party_id": party_id, "username": "Host", "client_id": "host-client"},
    )
    await asyncio.sleep(0.05)
    await realtime.emit(
        "select_video",
        {"party_id": party_id, "item_id": "movie-1", "item_name": "Fake Movie"},
    )
    await asyncio.sleep(0.3)
    return client, realtime, party_id


async def _start_ticks(fake_url: str) -> list[int]:
    """StartTimeTicks on every PlaybackInfo the fake Emby was asked for."""
    async with httpx.AsyncClient() as probe:
        response = await probe.get(f"{fake_url}/__test__/requests")
    recorded = response.json()["requests"]
    ticks = []
    for row in recorded:
        if not row["path"].endswith("/PlaybackInfo"):
            continue
        for key, value in row["query"]:
            if key == "StartTimeTicks":
                ticks.append(int(value))
    return ticks


async def _exercise_clamped(base_url: str, fake_url: str) -> None:
    client, realtime, party_id = await _playing_host(base_url)
    changed: list[dict] = []

    @realtime.on("streams_changed")
    async def on_changed(data):
        changed.append(data)

    try:
        # Park the party clock past the end of this source. Reached in
        # practice by switching from a longer version to a shorter one.
        # report_progress, not seek: select_video opens a ready check and
        # commit_seek refuses while one is active, so a seek here is dropped
        # and the clock silently stays at 0.
        await realtime.emit("report_progress", {"party_id": party_id, "time": 900.0})
        await asyncio.sleep(0.1)
        async with httpx.AsyncClient() as probe:
            await probe.post(f"{fake_url}/__test__/reset")

        await realtime.emit(
            "change_streams",
            {"party_id": party_id, "audio_index": 3, "subtitle_index": -1},
        )
        await asyncio.sleep(0.4)

        asked = await _start_ticks(fake_url)
        assert asked, "change_streams did not reach Emby at all"
        start_seconds = asked[-1] / 10_000_000
        # Inside the source, and close enough to where the party actually is
        # that nobody sees a rewind.
        assert start_seconds < MOVIE_RUN_TIME_SECONDS
        assert start_seconds >= MOVIE_RUN_TIME_SECONDS - 10

        # And the client is told where the stream really starts, not where the
        # party clock is. It maps this stream's t=0 onto this number, so the
        # raw clock left the viewer's reported position minutes ahead of the
        # frame actually on screen, with drift correction fighting the gap.
        assert changed, "the switcher was never told their stream changed"
        assert changed[-1]["current_time"] == start_seconds
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_change_streams_clamps_a_start_past_the_end_of_media(live_watchparty) -> None:
    asyncio.run(_exercise_clamped(live_watchparty.url, live_watchparty.fake.url))


async def _exercise_keeps_position(base_url: str, fake_url: str) -> None:
    client, realtime, party_id = await _playing_host(base_url)
    try:
        await realtime.emit("report_progress", {"party_id": party_id, "time": 120.0})
        await asyncio.sleep(0.1)
        async with httpx.AsyncClient() as probe:
            await probe.post(f"{fake_url}/__test__/reset")

        await realtime.emit(
            "change_streams",
            {"party_id": party_id, "audio_index": 3, "subtitle_index": -1},
        )
        await asyncio.sleep(0.4)

        asked = await _start_ticks(fake_url)
        assert asked, "change_streams did not reach Emby at all"
        # A clamp that fires when it should not is the other failure: it drags
        # the switcher backwards from where the party is watching.
        assert abs(asked[-1] / 10_000_000 - 120.0) < 5.0
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_change_streams_keeps_a_position_inside_the_source(live_watchparty) -> None:
    asyncio.run(_exercise_keeps_position(live_watchparty.url, live_watchparty.fake.url))
