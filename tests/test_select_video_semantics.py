"""Two select_video rules that the suite could not see being broken.

Both are decisions the server makes on behalf of the whole room, and both fail
quietly: the video plays either way, so nothing on screen says the wrong thing
happened.

  - `resume_mode` is the answer to the Resume / Start over prompt. Honouring
    it backwards, or dropping it, restarts a film everyone wanted to continue
    or drops them an hour in.
  - `binge` is host-only. Without the host check any joined member can flip
    the party-wide binge state, which arms the auto-advance countdown for
    everyone.
"""

import asyncio

import httpx
import socketio


async def _member(base_url: str, party_id: str, client_id: str, name: str):
    client = httpx.AsyncClient(base_url=base_url)
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": client_id, "display_name": name},
    )
    cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
    realtime = socketio.AsyncClient()
    await realtime.connect(base_url, headers={"Cookie": cookie})
    await realtime.emit(
        "join_party",
        {"party_id": party_id, "username": name, "client_id": client_id},
    )
    await asyncio.sleep(0.05)
    return client, realtime


async def _host(base_url: str):
    client = httpx.AsyncClient(base_url=base_url)
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "host-client", "display_name": "Host"},
    )
    login = await client.post(
        "/api/v2/auth/login", json={"username": "Host", "password": "password"}
    )
    assert login.json()["success"] is True
    cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
    realtime = socketio.AsyncClient()
    await realtime.connect(base_url, headers={"Cookie": cookie})
    await realtime.emit(
        "join_party",
        {"party_id": party_id, "username": "Host", "client_id": "host-client"},
    )
    await asyncio.sleep(0.05)
    return client, realtime, party_id


async def _last_start_ticks(fake_url: str) -> int:
    """StartTimeTicks on the most recent PlaybackInfo the fake Emby saw."""
    async with httpx.AsyncClient() as probe:
        response = await probe.get(f"{fake_url}/__test__/requests")
    ticks = [
        int(value)
        for row in response.json()["requests"]
        if row["path"].endswith("/PlaybackInfo")
        for key, value in row["query"]
        if key == "StartTimeTicks"
    ]
    assert ticks, "select_video never reached Emby"
    return ticks[-1]


async def _select(realtime, party_id: str, **extra) -> None:
    await realtime.emit(
        "select_video",
        {
            "party_id": party_id,
            "item_id": "movie-1",
            "item_name": "Fake Movie",
            **extra,
        },
    )
    await asyncio.sleep(0.4)


async def _exercise_resume(base_url: str, fake_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    try:
        await _select(realtime, party_id, start_seconds=300.0, resume_mode="resume")
        assert await _last_start_ticks(fake_url) == 300 * 10_000_000
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_resume_starts_where_the_viewer_left_off(live_watchparty) -> None:
    asyncio.run(_exercise_resume(live_watchparty.url, live_watchparty.fake.url))


async def _exercise_start_over(base_url: str, fake_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    try:
        # The offset is still sent -- the client does not clear it, the server
        # is what honours the choice -- so this is the branch that decides.
        await _select(realtime, party_id, start_seconds=300.0, resume_mode="start_over")
        assert await _last_start_ticks(fake_url) == 0
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_start_over_ignores_the_stored_position(live_watchparty) -> None:
    asyncio.run(_exercise_start_over(live_watchparty.url, live_watchparty.fake.url))


async def _binge_states(realtime) -> list[dict]:
    seen: list[dict] = []

    @realtime.on("binge_watch_state_changed")
    async def on_binge(data):
        seen.append(data)

    return seen


async def _exercise_binge_host_only(base_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    guest_client, guest_realtime = await _member(base_url, party_id, "guest-client", "Guest")
    host_seen = await _binge_states(realtime)
    guest_seen = await _binge_states(guest_realtime)
    try:
        # A guest selecting a video may set the video; it must not touch the
        # party-wide binge state, which arms auto-advance for everyone.
        await _select(guest_realtime, party_id, binge=True)
        assert host_seen == []
        assert guest_seen == []

        # The host's flag is acted on. BINGE_WATCH_ENABLED defaults off and
        # the fixture does not turn it on, so `active` is False here whatever
        # the host asks for -- the gate under test is whether the request is
        # honoured at all, and a guest's produces no event whatsoever.
        await _select(realtime, party_id, binge=True)
        assert host_seen, "the host's own binge flag was ignored too"
        assert host_seen[-1]["available"] is False
        assert guest_seen == host_seen, "the room should see the same state"
    finally:
        await guest_realtime.disconnect()
        await guest_client.aclose()
        await realtime.disconnect()
        await client.aclose()


def test_only_the_host_can_arm_binge_watching(live_watchparty) -> None:
    asyncio.run(_exercise_binge_host_only(live_watchparty.url))


async def _configure_fake(fake_url: str, payload: dict) -> None:
    async with httpx.AsyncClient() as controls:
        response = await controls.post(f"{fake_url}/__test__/behavior", json=payload)
        response.raise_for_status()


async def _exercise_loading_lifecycle(base_url: str, fake_url: str) -> None:
    await _configure_fake(
        fake_url,
        {"delays_ms": {"/emby/Items/movie-1/PlaybackInfo": 700}},
    )
    client, realtime, party_id = await _host(base_url)
    seen: list[tuple[str, dict]] = []
    realtime.on("video_selection_started", lambda data: seen.append(("started", data)))
    realtime.on("video_selected", lambda data: seen.append(("selected", data)))
    guest_client = httpx.AsyncClient(base_url=base_url)
    guest_realtime = socketio.AsyncClient()
    sync_states: list[dict] = []
    try:
        await realtime.emit(
            "select_video",
            {
                "party_id": party_id,
                "selection_id": "selection-delayed",
                "item_id": "movie-1",
                "item_name": "Fake Movie",
                "production_year": 2024,
                "run_time_seconds": 2700,
                "item_type": "Movie",
            },
        )
        await asyncio.sleep(0.15)
        assert [name for name, _ in seen] == ["started"]
        selection = seen[0][1]["selection"]
        assert selection["title"] == "Fake Movie"
        assert selection["production_year"] == 2024

        await guest_client.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "rejoin-client", "display_name": "Rejoin"},
        )
        cookie = "; ".join(f"{key}={value}" for key, value in guest_client.cookies.items())
        guest_realtime.on("sync_state", lambda data: sync_states.append(data))
        await guest_realtime.connect(base_url, headers={"Cookie": cookie})
        await guest_realtime.emit(
            "join_party",
            {"party_id": party_id, "username": "Rejoin", "client_id": "rejoin-client"},
        )
        await asyncio.sleep(0.15)
        assert sync_states[-1]["pending_video_selection"]["selection_id"] == "selection-delayed"
        assert sync_states[-1]["pending_video_selection"]["status"] == "preparing"

        await asyncio.sleep(1.4)
        assert [name for name, _ in seen][:2] == ["started", "selected"]
    finally:
        if guest_realtime.connected:
            await guest_realtime.disconnect()
        await guest_client.aclose()
        await realtime.disconnect()
        await client.aclose()


def test_selection_loading_precedes_video_and_survives_reconnect(live_watchparty) -> None:
    asyncio.run(_exercise_loading_lifecycle(live_watchparty.url, live_watchparty.fake.url))


async def _exercise_selection_failure(base_url: str, fake_url: str) -> None:
    await _configure_fake(
        fake_url,
        {"transient_failures": {"/emby/Items/movie-1/PlaybackInfo": 20}},
    )
    client, realtime, party_id = await _host(base_url)
    failed: list[dict] = []
    realtime.on("video_selection_failed", lambda data: failed.append(data))
    try:
        await _select(
            realtime,
            party_id,
            selection_id="selection-failed",
            start_seconds=300,
        )
        await asyncio.sleep(0.5)
        assert failed
        assert failed[-1]["selection"]["selection_id"] == "selection-failed"
        assert failed[-1]["selection"]["status"] == "failed"
        assert failed[-1]["message"] == "Could not start this video."
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_failed_selection_becomes_a_retryable_room_error(live_watchparty) -> None:
    asyncio.run(_exercise_selection_failure(live_watchparty.url, live_watchparty.fake.url))


async def _exercise_exact_retry(base_url: str, fake_url: str) -> None:
    await _configure_fake(
        fake_url,
        {"transient_failures": {"/emby/Items/movie-1/PlaybackInfo": 20}},
    )
    client, realtime, party_id = await _host(base_url)
    failed = asyncio.Event()
    selected = asyncio.Event()
    realtime.on("video_selection_failed", lambda _data: failed.set())
    realtime.on("video_selected", lambda _data: selected.set())
    try:
        await realtime.emit(
            "select_video",
            {
                "party_id": party_id,
                "selection_id": "selection-retry",
                "item_id": "movie-1",
                "item_name": "Fake Movie",
                "start_seconds": 300,
                "resume_mode": "resume",
                "media_source_id": "source-1",
                "quality": "720p-medium",
                "audio_index": 1,
                "subtitle_index": -1,
                "binge": True,
            },
        )
        await asyncio.wait_for(failed.wait(), timeout=2)
        async with httpx.AsyncClient() as controls:
            await controls.post(f"{fake_url}/__test__/reset")
        await realtime.emit(
            "retry_video_selection",
            {"party_id": party_id, "selection_id": "selection-retry"},
        )
        await asyncio.wait_for(selected.wait(), timeout=3)
        assert await _last_start_ticks(fake_url) == 300 * 10_000_000
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_selector_retry_replays_the_exact_start_offset(live_watchparty) -> None:
    asyncio.run(_exercise_exact_retry(live_watchparty.url, live_watchparty.fake.url))


async def _exercise_cancel_race(base_url: str, fake_url: str) -> None:
    await _configure_fake(
        fake_url,
        {"delays_ms": {"/emby/Items/movie-1/PlaybackInfo": 700}},
    )
    client, realtime, party_id = await _host(base_url)
    started = asyncio.Event()
    selected: list[dict] = []
    cancelled: list[dict] = []
    realtime.on("video_selection_started", lambda _data: started.set())
    realtime.on("video_selected", lambda data: selected.append(data))
    realtime.on("video_selection_cancelled", lambda data: cancelled.append(data))
    try:
        await realtime.emit(
            "select_video",
            {
                "party_id": party_id,
                "selection_id": "selection-cancelled",
                "item_id": "movie-1",
                "item_name": "Fake Movie",
            },
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await realtime.emit(
            "cancel_video_selection",
            {"party_id": party_id, "selection_id": "selection-cancelled"},
        )
        await asyncio.sleep(1.1)
        assert cancelled == [{"selection_id": "selection-cancelled"}]
        assert selected == []
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_cancel_aborts_preparation_and_blocks_late_video_selected(live_watchparty) -> None:
    asyncio.run(_exercise_cancel_race(live_watchparty.url, live_watchparty.fake.url))
