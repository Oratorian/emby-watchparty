"""Host-controlled visibility of a party in the public index listing.

Parties are created hidden and stay off `/api/party/list` until their host
opts in. "Hidden" means unlisted, not private: the code still joins, exactly
as an unlisted link works elsewhere.

Two properties here are worth more than the happy path. The listing is the
only thing that reveals a party to someone who was not given the code, so a
non-host being able to flip it back on is a real exposure, not a UI bug. And
the change is broadcast to the room rather than answered to the caller,
because a host with the party open in two tabs would otherwise leave a stale
switch in the other one, misreporting whether they are advertised.
"""

import asyncio

import httpx
import pytest
import socketio


async def _member(base_url: str, party_id: str, client_id: str, name: str):
    """Join an existing party over HTTP, then attach a socket to it."""
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
    """Create a party and promote the creator to host via the real login."""
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
    return client, realtime, party_id


async def _listed_codes(client: httpx.AsyncClient) -> list[str]:
    listing = await client.get("/api/party/list")
    return [item["code"] for item in listing.json()["parties"]]


async def _exercise_starts_hidden(base_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    try:
        # A party with a member and a logged-in host, which is everything the
        # listing used to require, is still absent until someone opts in.
        assert party_id not in await _listed_codes(client)

        await realtime.emit("set_party_hidden", {"party_id": party_id, "hidden": False})
        await asyncio.sleep(0.05)
        assert party_id in await _listed_codes(client)

        await realtime.emit("set_party_hidden", {"party_id": party_id, "hidden": True})
        await asyncio.sleep(0.05)
        assert party_id not in await _listed_codes(client)
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_party_starts_hidden_and_the_host_toggles_the_listing(live_watchparty) -> None:
    asyncio.run(_exercise_starts_hidden(live_watchparty.url))


async def _exercise_hidden_party_still_joins(base_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    guest = httpx.AsyncClient(base_url=base_url)
    try:
        assert party_id not in await _listed_codes(client)

        # Unlisted, not private. Someone holding the code joins as always.
        exists = await guest.get(f"/api/party/{party_id}/exists")
        assert exists.json() == {"exists": True}
        joined = await guest.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "guest-client", "display_name": "Guest"},
        )
        assert joined.json()["success"] is True
    finally:
        await guest.aclose()
        await realtime.disconnect()
        await client.aclose()


def test_a_hidden_party_is_unlisted_not_unreachable(live_watchparty) -> None:
    asyncio.run(_exercise_hidden_party_still_joins(live_watchparty.url))


async def _exercise_non_host_refused(base_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    guest_client, guest_realtime = await _member(base_url, party_id, "guest-client", "Guest")
    guest_events: list[dict] = []

    @guest_realtime.on("party_visibility_changed")
    async def on_guest_visibility(data):
        guest_events.append(data)

    try:
        await realtime.emit("set_party_hidden", {"party_id": party_id, "hidden": False})
        await asyncio.sleep(0.05)
        guest_events.clear()
        assert party_id in await _listed_codes(client)

        # The button is not rendered for a guest, so this is a client that
        # should not have sent it. It gets no reply and changes nothing.
        await guest_realtime.emit("set_party_hidden", {"party_id": party_id, "hidden": True})
        await asyncio.sleep(0.1)

        assert party_id in await _listed_codes(client)
        assert guest_events == []
    finally:
        await guest_realtime.disconnect()
        await guest_client.aclose()
        await realtime.disconnect()
        await client.aclose()


def test_a_non_host_cannot_change_visibility(live_watchparty) -> None:
    asyncio.run(_exercise_non_host_refused(live_watchparty.url))


async def _exercise_broadcast(base_url: str) -> None:
    client, realtime, party_id = await _host(base_url)
    guest_client, guest_realtime = await _member(base_url, party_id, "guest-client", "Guest")
    seen: list[dict] = []
    received = asyncio.Event()

    # Stands in for the host's second tab: it is another socket in the room,
    # and answering only the caller would leave its switch stale.
    @guest_realtime.on("party_visibility_changed")
    async def on_visibility(data):
        seen.append(data)
        received.set()

    try:
        await realtime.emit("set_party_hidden", {"party_id": party_id, "hidden": False})
        await asyncio.wait_for(received.wait(), timeout=2)
        assert seen == [{"hidden": False}]
    finally:
        await guest_realtime.disconnect()
        await guest_client.aclose()
        await realtime.disconnect()
        await client.aclose()


def test_visibility_change_reaches_the_whole_room(live_watchparty) -> None:
    asyncio.run(_exercise_broadcast(live_watchparty.url))


async def _exercise_sync_state(base_url: str, hidden: bool) -> None:
    client, realtime, party_id = await _host(base_url)
    try:
        await realtime.emit("set_party_hidden", {"party_id": party_id, "hidden": hidden})
        await asyncio.sleep(0.05)

        # A joiner renders the switch from sync_state. Without `hidden` on it,
        # a second tab opens showing the party as hidden while it is listed.
        # Both polarities, because SyncStateOutbound defaults the field to
        # False: asserting only the False case passes against a payload that
        # never carries the real value at all.
        states: list[dict] = []
        arrived = asyncio.Event()
        late_client, late_realtime = None, None
        late_client = httpx.AsyncClient(base_url=base_url)
        await late_client.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "late-client", "display_name": "Late"},
        )
        cookie = "; ".join(f"{key}={value}" for key, value in late_client.cookies.items())
        late_realtime = socketio.AsyncClient()
        await late_realtime.connect(base_url, headers={"Cookie": cookie})

        @late_realtime.on("sync_state")
        async def on_sync(data):
            states.append(data)
            arrived.set()

        await late_realtime.emit(
            "join_party",
            {"party_id": party_id, "username": "Late", "client_id": "late-client"},
        )
        try:
            await asyncio.wait_for(arrived.wait(), timeout=2)
            assert states[0]["hidden"] is hidden
        finally:
            await late_realtime.disconnect()
            await late_client.aclose()
    finally:
        await realtime.disconnect()
        await client.aclose()


@pytest.mark.parametrize("hidden", [True, False])
def test_sync_state_carries_the_current_visibility(live_watchparty, hidden) -> None:
    asyncio.run(_exercise_sync_state(live_watchparty.url, hidden))
