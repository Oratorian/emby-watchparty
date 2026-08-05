from __future__ import annotations

import asyncio
from time import perf_counter
from urllib.parse import urljoin

import httpx
import socketio


def _media_line(playlist: str) -> str:
    return next(line for line in playlist.splitlines() if line and not line.startswith("#"))


def _shout_extension(url: str) -> str:
    """Uppercase the path's extension, leaving the query string alone.

    The token is case-sensitive, so only the part before `?` is touched.
    """
    path, separator, query = url.partition("?")
    return path.replace(".m3u8", ".M3U8") + separator + query


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
        assert ranged.headers["content-range"] == "bytes 0-17/168260"
        assert len(ranged.content) == 18
        assert ranged.headers["accept-ranges"] == "bytes"
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_live_hls_streams_first_chunk_and_forwards_ios_range(live_watchparty) -> None:
    asyncio.run(_exercise_streaming_and_range(live_watchparty))


async def _exercise_uppercase_playlist_extension(live_watchparty) -> None:
    """An uppercase extension must not skip playlist handling.

    `_safe_hls_subpath` never inspects the extension, so `main.M3U8`
    reached the segment streamer and the raw upstream body was returned
    verbatim: `_safe_upstream_playlist_uri` never ran over its lines, and
    no token was appended to the child URIs it advertises.

    What this test can demonstrate is the content type and the missing
    token, which is what breaks first. The skipped URI validation is the
    security half and does not show up here, because the fake's fixtures
    use bare relative names; real Emby emits absolute `/emby/Videos/`
    forms, which is why `_rewrite_playlist` carries two regexes for them.
    The `/emby/Videos/` assertion below is therefore a regression guard,
    not the demonstration.
    """
    client, realtime, master_url = await _select_video(live_watchparty.url)
    try:
        master = await client.get(master_url)
        assert master.status_code == 200
        variant_url = urljoin(master_url, _media_line(master.text))

        shouted = await client.get(_shout_extension(variant_url))
        assert shouted.status_code == 200
        assert shouted.headers["content-type"].startswith("application/vnd.apple.mpegurl")
        # Rewritten, so no upstream path survives...
        assert "/emby/Videos/" not in shouted.text
        # ...and the child URI still carries a token to be authorised with.
        assert "token=" in _media_line(shouted.text)

        lowercase = await client.get(variant_url)
        assert _media_line(shouted.text) == _media_line(lowercase.text)
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_uppercase_playlist_extension_is_still_rewritten(live_watchparty) -> None:
    asyncio.run(_exercise_uppercase_playlist_extension(live_watchparty))


async def _exercise_tokenless_development_playback(live_watchparty) -> None:
    client, realtime, master_url = await _select_video(live_watchparty.url)
    try:
        assert "token=" not in master_url

        master = await client.get(master_url)
        assert master.status_code == 200
        variant_url = urljoin(master_url, _media_line(master.text))
        assert "token=" not in variant_url

        variant = await client.get(variant_url)
        assert variant.status_code == 200
        segment_url = urljoin(variant_url, _media_line(variant.text))
        assert (await client.get(segment_url)).status_code == 200

        async with httpx.AsyncClient(base_url=live_watchparty.url) as unrelated:
            assert (await unrelated.get(master_url)).status_code == 401
    finally:
        await realtime.disconnect()
        await client.aclose()


def test_hls_disabled_development_uses_party_session(live_watchparty_hls_disabled) -> None:
    asyncio.run(_exercise_tokenless_development_playback(live_watchparty_hls_disabled))


async def _exercise_hls_requires_matching_party_session(live_watchparty) -> None:
    owner, owner_realtime, master_url = await _select_video(live_watchparty.url)
    other, other_realtime, _ = await _select_video(live_watchparty.url)
    try:
        async with httpx.AsyncClient(base_url=live_watchparty.url) as anonymous:
            assert (await anonymous.get(master_url)).status_code == 401
        assert (await other.get(master_url)).status_code == 401
        assert (await owner.get(master_url)).status_code == 200
    finally:
        await owner_realtime.disconnect()
        await other_realtime.disconnect()
        await owner.aclose()
        await other.aclose()


def test_hls_requires_cookie_for_same_party_as_token(live_watchparty) -> None:
    asyncio.run(_exercise_hls_requires_matching_party_session(live_watchparty))


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
    await client.post("/api/auth/login", json={"username": "Alice", "password": "password"})
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


async def _exercise_playlist_fidelity_and_security(live_watchparty) -> None:
    client, realtime, master_url = await _select_video(live_watchparty.url)
    controls = httpx.AsyncClient(base_url=live_watchparty.fake.url)
    try:
        crlf = "#EXTM3U\r\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\r\nmain.m3u8?PlaySessionId=one\r\n"
        await controls.post("/__test__/behavior", json={"master_playlist": crlf})
        duplicate_url = f"{master_url}&AudioCodec=aac&AudioCodec=mp3"
        response = await client.get(duplicate_url)
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers
        assert response.content.endswith(b"\r\n")
        assert b"\r\n" in response.content
        recorded = (await controls.get("/__test__/requests")).json()["requests"]
        master_request = next(
            row for row in reversed(recorded) if row["path"].endswith("/master.m3u8")
        )
        audio_codecs = [value for key, value in master_request["query"] if key == "AudioCodec"]
        assert audio_codecs[-2:] == ["aac", "mp3"]

        lf_without_terminator = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\nmain.m3u8"
        await controls.post("/__test__/behavior", json={"master_playlist": lf_without_terminator})
        response = await client.get(master_url)
        assert response.status_code == 200
        assert "\r\n" not in response.text
        assert not response.text.endswith("\n")

        for upstream_uri in (
            f"{live_watchparty.fake.url}/emby/Videos/movie-1/main.m3u8",
            "/emby/Videos/movie-1/main.m3u8",
        ):
            await controls.post(
                "/__test__/behavior",
                json={"master_playlist": f"#EXTM3U\n{upstream_uri}\n"},
            )
            rewritten = await client.get(master_url)
            assert rewritten.status_code == 200
            assert _media_line(rewritten.text).startswith("/hls/movie-1/main.m3u8")

        for unsafe_uri in ("../outside.ts", "segment%2501.ts"):
            await controls.post(
                "/__test__/behavior",
                json={"master_playlist": f"#EXTM3U\n{unsafe_uri}\n"},
            )
            unsafe_playlist = await client.get(master_url)
            assert unsafe_playlist.status_code == 502

        rejected_query = await client.get(f"{master_url}&api_key=not-allowed")
        assert rejected_query.status_code == 400
        rejected_control = await client.get(
            master_url.replace("master.m3u8", "nested%252f..%252fsecret.ts")
        )
        assert rejected_control.status_code == 400
    finally:
        await realtime.disconnect()
        await client.aclose()
        await controls.aclose()


def test_live_playlist_preserves_format_and_rejects_unsafe_inputs(live_watchparty) -> None:
    asyncio.run(_exercise_playlist_fidelity_and_security(live_watchparty))
