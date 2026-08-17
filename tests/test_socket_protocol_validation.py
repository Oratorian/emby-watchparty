import asyncio

import httpx
import socketio


async def _connected_member(base_url: str):
    client = httpx.AsyncClient(base_url=base_url)
    created = await client.post("/api/party/create", json={})
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "client-1", "display_name": "Alice"},
    )
    cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
    realtime = socketio.AsyncClient()
    await realtime.connect(base_url, headers={"Cookie": cookie})
    await realtime.emit(
        "join_party",
        {"party_id": party_id, "username": "Alice", "client_id": "client-1"},
    )
    await asyncio.sleep(0.02)
    return client, realtime, party_id


async def _exercise_invalid_payload(base_url: str) -> None:
    client, realtime, party_id = await _connected_member(base_url)
    error = asyncio.Event()
    messages: list[str] = []

    @realtime.on("error")
    async def on_error(data):
        messages.append(data["message"])
        error.set()

    try:
        await realtime.emit("seek", {"party_id": party_id})
        await asyncio.wait_for(error.wait(), timeout=2)
        assert "Invalid seek payload" in messages[0]
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_invalid_socket_payload_uses_existing_error_event(live_watchparty) -> None:
    asyncio.run(_exercise_invalid_payload(live_watchparty.url))


async def _exercise_unknown_field(base_url: str) -> None:
    client, realtime, party_id = await _connected_member(base_url)
    received = asyncio.Event()

    @realtime.on("seek")
    async def on_seek(_data):
        received.set()

    try:
        await realtime.emit(
            "seek",
            {"party_id": party_id, "time": 12.5, "future_field": True},
        )
        await asyncio.wait_for(received.wait(), timeout=2)
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_unknown_socket_fields_remain_compatible(live_watchparty) -> None:
    asyncio.run(_exercise_unknown_field(live_watchparty.url))


async def _exercise_identity_claim(base_url: str) -> None:
    client, owner, party_id = await _connected_member(base_url)
    attacker = socketio.AsyncClient()
    rejected = asyncio.Event()

    @attacker.on("error")
    async def on_error(data):
        if data["message"] == "Participant identity is already in use":
            rejected.set()

    await attacker.connect(base_url)
    try:
        await attacker.emit(
            "join_party",
            {"party_id": party_id, "username": "Mallory", "client_id": "client-1"},
        )
        await asyncio.wait_for(rejected.wait(), timeout=2)
    finally:
        await attacker.disconnect()
        await owner.disconnect()
        await client.aclose()


def test_socket_cannot_claim_existing_participant_identity(live_watchparty) -> None:
    asyncio.run(_exercise_identity_claim(live_watchparty.url))


async def _exercise_preclaimed_host_identity(base_url: str) -> None:
    host = httpx.AsyncClient(base_url=base_url)
    attacker_http = httpx.AsyncClient(base_url=base_url)
    attacker_socket = socketio.AsyncClient()
    rejected = asyncio.Event()

    try:
        created = await host.post("/api/party/create", json={})
        party_id = created.json()["party_id"]
        identity = {"client_id": "future-host", "display_name": "Alice"}
        await host.post(f"/api/party/{party_id}/join", json=identity)
        await attacker_http.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "future-host", "display_name": "Mallory"},
        )
        login = await host.post(
            "/api/v2/auth/login",
            json={"username": "Alice", "password": "password"},
        )
        assert login.json()["is_host"] is True

        @attacker_socket.on("error")
        async def on_error(data):
            if data["message"] == "Participant identity is already in use":
                rejected.set()

        cookie = "; ".join(f"{key}={value}" for key, value in attacker_http.cookies.items())
        await attacker_socket.connect(base_url, headers={"Cookie": cookie})
        await attacker_socket.emit(
            "join_party",
            {"party_id": party_id, "username": "Mallory", "client_id": "future-host"},
        )
        await asyncio.wait_for(rejected.wait(), timeout=2)
    finally:
        if attacker_socket.connected:
            await attacker_socket.disconnect()
        await attacker_http.aclose()
        await host.aclose()


def test_socket_preclaim_cannot_take_future_host_identity(live_watchparty) -> None:
    asyncio.run(_exercise_preclaimed_host_identity(live_watchparty.url))
