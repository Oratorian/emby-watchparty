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
