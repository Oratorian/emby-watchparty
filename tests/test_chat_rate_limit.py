import asyncio

import httpx
import socketio


async def _exercise_chat_limit(live_watchparty) -> None:
    async with httpx.AsyncClient(base_url=live_watchparty.url) as client:
        created = await client.post("/api/party/create", json={})
        party_id = created.json()["party_id"]
        await client.post(
            f"/api/party/{party_id}/join",
            json={"client_id": "chat-client", "display_name": "Alice"},
        )
        cookie = "; ".join(
            f"{name}={value}" for name, value in client.cookies.items()
        )

        realtime = socketio.AsyncClient()
        messages: list[str] = []

        @realtime.on("chat_message")
        async def receive_chat(data):
            messages.append(data["message"])

        await realtime.connect(live_watchparty.url, headers={"Cookie": cookie})
        await realtime.emit("join_party", {
            "party_id": party_id,
            "username": "Alice",
            "client_id": "chat-client",
        })
        await asyncio.sleep(0.05)

        for index in range(6):
            await realtime.emit("chat_message", {
                "party_id": party_id,
                "message": f"burst-{index}",
            })
        await asyncio.sleep(0.15)
        assert messages == [f"burst-{index}" for index in range(5)]

        await asyncio.sleep(3.05)
        await realtime.emit("chat_message", {
            "party_id": party_id,
            "message": "after-expiry",
        })
        await asyncio.sleep(0.15)
        assert messages[-1] == "after-expiry"
        assert len(messages) == 6

        await realtime.emit("leave_party", {"party_id": party_id})
        await realtime.disconnect()


def test_chat_limit_caps_bursts_and_expires(live_watchparty) -> None:
    asyncio.run(_exercise_chat_limit(live_watchparty))
