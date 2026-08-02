"""Protocol-faithful, loopback-only Emby test server."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse


MOVIE = {
    "Id": "movie-1",
    "Name": "Fake Movie",
    "Type": "Movie",
    "Overview": "A deterministic movie served by fake Emby.",
    "RunTimeTicks": 6_000_000_000,
    "MediaSourceCount": 1,
    "UserData": {"PlaybackPositionTicks": 0, "Played": False},
    "MediaSources": [
        {
            "Id": "source-1",
            "Name": "Fake Source",
            "Container": "mkv",
            "RunTimeTicks": 6_000_000_000,
            "MediaStreams": [
                {
                    "Index": 0,
                    "Type": "Video",
                    "Codec": "h264",
                    "Width": 1920,
                    "Height": 1080,
                    "BitRate": 4_000_000,
                },
                {
                    "Index": 1,
                    "Type": "Audio",
                    "Codec": "aac",
                    "Language": "eng",
                    "DisplayTitle": "English AAC",
                },
            ],
        }
    ],
}


@dataclass
class FakeEmbyBehavior:
    delays_ms: dict[str, int] = field(default_factory=dict)
    transient_failures: dict[str, int] = field(default_factory=dict)
    transient_status: int = 503
    segment_chunks: list[bytes] = field(
        default_factory=lambda: [b"fake-segment-first", b"fake-segment-last"]
    )
    segment_delay_ms: int = 0
    master_playlist: str = (
        "#EXTM3U\r\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\r\nmain.m3u8\r\n"
    )
    variant_playlist: str = "#EXTM3U\r\n#EXTINF:1.0,\r\nsegment0.ts\r\n"


@dataclass
class FakeEmbyState:
    behavior: FakeEmbyBehavior = field(default_factory=FakeEmbyBehavior)
    requests: list[dict[str, Any]] = field(default_factory=list)
    stream_closed: asyncio.Event = field(default_factory=asyncio.Event)

    def record(self, request: Request, *, body: Any = None) -> None:
        row: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "query": list(request.query_params.multi_items()),
        }
        if body is not None:
            row["body"] = body
        self.requests.append(row)

    async def before(self, request: Request) -> Response | None:
        path = request.url.path
        delay = self.behavior.delays_ms.get(path, 0)
        if delay:
            await asyncio.sleep(delay / 1000)
        remaining = self.behavior.transient_failures.get(path, 0)
        if remaining > 0:
            self.behavior.transient_failures[path] = remaining - 1
            return Response(status_code=self.behavior.transient_status)
        return None


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="test controls are loopback-only")


def create_fake_emby_app(state: FakeEmbyState | None = None) -> FastAPI:
    state = state or FakeEmbyState()
    app = FastAPI(title="Fake Emby", docs_url=None, redoc_url=None)
    app.state.fake_emby = state

    @app.get("/__test__/requests")
    async def recorded_requests(request: Request):
        _require_loopback(request)
        return {"requests": state.requests}

    @app.get("/__test__/state")
    async def observable_state(request: Request):
        _require_loopback(request)
        return {"stream_closed": state.stream_closed.is_set()}

    @app.post("/__test__/reset")
    async def reset(request: Request):
        _require_loopback(request)
        state.requests.clear()
        state.behavior = FakeEmbyBehavior()
        state.stream_closed = asyncio.Event()
        return {"success": True}

    @app.post("/__test__/behavior")
    async def configure_behavior(request: Request):
        _require_loopback(request)
        data = await request.json()
        state.behavior.delays_ms = dict(data.get("delays_ms", {}))
        state.behavior.transient_failures = dict(data.get("transient_failures", {}))
        state.behavior.transient_status = int(data.get("transient_status", 503))
        state.behavior.segment_delay_ms = int(data.get("segment_delay_ms", 0))
        if "master_playlist" in data:
            state.behavior.master_playlist = str(data["master_playlist"])
        if "variant_playlist" in data:
            state.behavior.variant_playlist = str(data["variant_playlist"])
        return {"success": True}

    @app.get("/emby/System/Info/Public")
    async def system_info(request: Request):
        state.record(request)
        if failure := await state.before(request):
            return failure
        return {"ServerName": "Fake Emby", "Version": "4.9.0"}

    @app.post("/emby/Users/AuthenticateByName")
    async def authenticate(request: Request):
        state.record(request)  # Never retain submitted credentials.
        if failure := await state.before(request):
            return failure
        return {
            "AccessToken": "fake-access-token",
            "User": {
                "Id": "user-1",
                "Name": "Alice",
                "Policy": {"IsAdministrator": True},
            },
        }

    @app.post("/emby/Sessions/Capabilities/Full")
    async def capabilities(request: Request):
        state.record(request)
        return {}

    @app.get("/emby/Users/{user_id}")
    async def user(request: Request, user_id: str):
        state.record(request)
        return {"Id": user_id, "Name": "Alice"}

    @app.get("/emby/Users/{user_id}/Views")
    async def views(request: Request, user_id: str):
        del user_id
        state.record(request)
        return {
            "Items": [
                {
                    "Id": "library-1",
                    "Name": "Movies",
                    "Type": "CollectionFolder",
                    "CollectionType": "movies",
                }
            ],
            "TotalRecordCount": 1,
        }

    @app.get("/emby/Library/MediaFolders")
    async def media_folders(request: Request):
        state.record(request)
        return {
            "Items": [
                {"Id": "library-1", "Name": "Movies", "CollectionType": "movies"}
            ]
        }

    @app.get("/emby/Users/{user_id}/Items")
    async def user_items(request: Request, user_id: str):
        del user_id
        state.record(request)
        return {"Items": [MOVIE], "TotalRecordCount": 1}

    @app.get("/emby/Items")
    async def items(request: Request):
        state.record(request)
        return {"Items": [MOVIE], "TotalRecordCount": 1}

    @app.get("/emby/Users/{user_id}/Items/{item_id}")
    async def user_item(request: Request, user_id: str, item_id: str):
        del user_id
        state.record(request)
        return {**MOVIE, "Id": item_id}

    @app.get("/emby/Items/{item_id}")
    async def item(request: Request, item_id: str):
        state.record(request)
        return {**MOVIE, "Id": item_id}

    @app.post("/emby/Items/{item_id}/PlaybackInfo")
    async def playback_info(request: Request, item_id: str):
        state.record(request, body=await request.json())
        if failure := await state.before(request):
            return failure
        return {
            "PlaySessionId": "play-session-1",
            "MediaSources": [{**MOVIE["MediaSources"][0], "ItemId": item_id}],
        }

    @app.api_route("/emby/Sessions/Playing{suffix:path}", methods=["POST"])
    async def playback_report(request: Request, suffix: str):
        del suffix
        state.record(request, body=await request.json())
        return {}

    @app.delete("/emby/Videos/ActiveEncodings")
    async def stop_transcode(request: Request):
        state.record(request)
        return Response(status_code=204)

    @app.get("/emby/Videos/{item_id}/master.m3u8")
    async def master_playlist(request: Request, item_id: str):
        del item_id
        state.record(request)
        if failure := await state.before(request):
            return failure
        return Response(
            content=state.behavior.master_playlist,
            media_type="application/vnd.apple.mpegurl",
        )

    @app.get("/emby/Videos/{item_id}/main.m3u8")
    async def variant_playlist(request: Request, item_id: str):
        del item_id
        state.record(request)
        return Response(
            content=state.behavior.variant_playlist,
            media_type="application/vnd.apple.mpegurl",
        )

    @app.get("/emby/Videos/{item_id}/{segment_name}")
    async def segment(request: Request, item_id: str, segment_name: str):
        del item_id, segment_name
        state.record(request)

        async def body() -> AsyncIterator[bytes]:
            try:
                for chunk in state.behavior.segment_chunks:
                    yield chunk
                    if state.behavior.segment_delay_ms:
                        await asyncio.sleep(state.behavior.segment_delay_ms / 1000)
            finally:
                state.stream_closed.set()

        headers: dict[str, str] = {"Accept-Ranges": "bytes"}
        status = 200
        if request.headers.get("range"):
            status = 206
            headers["Content-Range"] = "bytes 0-17/36"
        return StreamingResponse(body(), status_code=status, media_type="video/MP2T", headers=headers)

    return app
